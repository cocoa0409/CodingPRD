"""Validation and rejection-ladder conformance for the royalty API.

The area under test is the ordered rejection ladder of PRD §2.10 together with
the individual validation rules it orders: authentication before role, role
before existence, existence before body structure, composite natural keys,
the three different interval geometries, the right-type/holder-type conjunction,
routing viability, the publishing split, the two non-degenerate-usage rules and
the open-claims gate on period closure.
"""

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    append_line,
    composition_payload,
    create_batch,
    create_collective,
    create_composition,
    create_holder,
    create_label,
    create_period,
    create_publisher,
    create_recording,
    file_registration,
    issue_statement,
    make_rights_holder_user_headers,
    period_payload,
    period_version,
    pool_payload,
    rate_schedule_payload,
    reject_registration,
    review_registration,
    rights_registration_payload,
    set_clock,
    setup_all_matched_pool_finalized,
    setup_all_matched_statement_drafted,
    statement_payload,
    usage_line_payload,
    validate_error,
    validate_success,
    work_payload,
    work_version,
)

# A pool create body that names a period but omits both required numbers, so it
# fails the priority-4 structural check on top of whatever else is wrong.
UNKNOWN_PERIOD_ID = "11111111-1111-4111-8111-111111111120"
UNKNOWN_PERIOD_ID_2 = "11111111-1111-4111-8111-111111111121"


def _pool_body_missing_numbers(period_id):
    """A pool create body carrying neither subscriber_count nor
    gross_revenue_cents, built from declared input fields only."""
    return {
        "period_id": period_id,
        "territory_code": "GB",
        "subscription_tier": "INDIVIDUAL",
    }


def _setup_distributed_period_with_open_rival_claim(api):
    """A DISTRIBUTED period whose holding account is empty, carrying one rival
    MASTER claim left in SUBMITTED, with the clock moved past the claim window.

    Composed from the atoms in the helper package: the all-matched usage
    fixture through to a finalized pool, one extra DISTRIBUTOR holder, and one
    further claim on the same recording filed while the window was still open.
    """
    fixture = setup_all_matched_pool_finalized(api)
    fixture["rival"] = create_holder(
        api,
        legal_name="Harborline Distribution",
        holder_type="DISTRIBUTOR",
        home_territory_code="GB",
        direct_deal_rate_bps=800,
    )
    fixture["rival_registration"] = file_registration(
        api,
        fixture["recording_a"]["id"],
        fixture["rival"]["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["GB"],
    )
    set_clock(api, "2026-08-30T00:00:00Z")
    return fixture


# ─────────────────────────────────────────────────────
# Ladder priority 1 — authentication
# ─────────────────────────────────────────────────────

def test_missing_identity_headers_outrank_role_existence_and_structure(
    api, royalty_admin_headers
):
    """A pool create with no identity headers, an unauthorized role, an unknown period and two missing required fields reports only ERR_UNAUTHENTICATED.

    PRD: "Authentication: `X-User-Role` and `X-User-ID` are present and the role is one of the four declared in §2.1 — otherwise `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/priority_1_authentication_outranks_role_existence_and_structure
    """
    response = api.create_pool(_pool_body_missing_numbers(UNKNOWN_PERIOD_ID), {})
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"]
    assert error["message"].strip()

    pools = validate_success(api.list_pools(royalty_admin_headers), 200)
    assert pools == [], "a rejected create must leave no pool row behind"


# ─────────────────────────────────────────────────────
# Ladder priority 2 — role authorization
# ─────────────────────────────────────────────────────

def test_role_refusal_outranks_duplicate_label_and_inverted_window(
    api, royalty_admin_headers
):
    """A RightsHolderUser creating a period with a duplicate label and an inverted usage window is refused for its role alone.

    PRD: "Role authorization: the supplied role appears in the target endpoint's authorized list — otherwise `ERR_FORBIDDEN_ROLE`."

    Design: Corner/validations/priority_2_role_outranks_existence_and_structure
    """
    label = create_label(api)
    incumbent = create_period(api)

    response = api.create_period(
        period_payload(
            label=TEST_DEFAULTS["PERIOD_LABEL"],
            usage_start="2026-06-30",
            usage_end="2026-06-01",
        ),
        make_rights_holder_user_headers(label["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    unchanged = validate_success(
        api.get_period(incumbent["id"], royalty_admin_headers), 200
    )
    assert unchanged["status"] == "OPEN"
    assert unchanged["label"] == TEST_DEFAULTS["PERIOD_LABEL"]
    assert unchanged["usage_start"] == TEST_DEFAULTS["PERIOD_USAGE_START"]
    assert unchanged["usage_end"] == TEST_DEFAULTS["PERIOD_USAGE_END"]
    assert unchanged["version"] == incumbent["version"]


# ─────────────────────────────────────────────────────
# Ladder priority 3 — existence before structure
# ─────────────────────────────────────────────────────

def test_unknown_foreign_key_outranks_missing_required_fields(api, royalty_admin_headers):
    """A pool create naming an unknown period reports ERR_PERIOD_NOT_FOUND even though two required numeric fields are absent, while the identical body against a real period reports ERR_INVALID_REQUEST.

    PRD: "The practical consequence worth internalizing: authorization precedes existence, existence precedes shape, shape precedes uniqueness, ownership and duty separation precede every state check, all state checks precede the concurrency check, and every business rule about money, time and territory comes last."

    Design: Corner/validations/priority_3_existence_outranks_priority_4_structure
    """
    unknown = api.create_pool(
        _pool_body_missing_numbers(UNKNOWN_PERIOD_ID_2), royalty_admin_headers
    )
    validate_error(unknown, ApiErrorId.ERR_PERIOD_NOT_FOUND.value, 404)

    period = create_period(api)
    structural = api.create_pool(
        _pool_body_missing_numbers(period["id"]), royalty_admin_headers
    )
    validate_error(structural, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    pools = validate_success(api.list_pools(royalty_admin_headers), 200)
    assert pools == [], "neither rejected create may leave a pool row behind"


# ─────────────────────────────────────────────────────
# Ladder priority 5 — composite natural keys
# ─────────────────────────────────────────────────────

def test_work_uniqueness_is_on_the_work_type_identifier_pair(
    api, rights_ops_analyst_headers
):
    """A second RECORDING reusing an identifier is refused while a COMPOSITION reusing the same identifier string is created.

    PRD: "A second recording claiming an existing `(work_type, identifier)` pair is refused with `ERR_DUPLICATE_WORK_IDENTIFIER`."

    Design: Corner/validations/duplicate_natural_keys_are_composite_not_single_column
    """
    recording = create_recording(api)
    assert recording["identifier"] == TEST_DEFAULTS["RECORDING_A_ISRC"]

    duplicate = api.create_work(
        work_payload(
            identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
            title="Midnight Ledger (Remaster)",
        ),
        rights_ops_analyst_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_WORK_IDENTIFIER.value, 409)

    recordings = validate_success(
        api.list_works(rights_ops_analyst_headers, params={"work_type": "RECORDING"}),
        200,
    )
    assert len(recordings) == 1, "the refused duplicate must leave no work row behind"

    composition = validate_success(
        api.create_work(
            composition_payload(
                identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
                title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            ),
            rights_ops_analyst_headers,
        ),
        201,
    )
    assert composition["work_type"] == "COMPOSITION"
    assert composition["identifier"] == TEST_DEFAULTS["RECORDING_A_ISRC"]


def test_period_uniqueness_is_on_the_label_alone(api, royalty_admin_headers):
    """A second period reusing an existing label is refused even with a completely different usage window.

    PRD: "A `RoyaltyAdmin` opens an **accounting period** with a `label` — a human name such as `2026-06`, unique across all periods, with a collision reported as `ERR_DUPLICATE_PERIOD_LABEL` — and the inclusive date range it covers, `usage_start` and `usage_end`, both ISO 8601 calendar dates."

    Design: Corner/validations/duplicate_natural_keys_are_composite_not_single_column
    """
    incumbent = create_period(api)

    duplicate = api.create_period(
        period_payload(
            label=TEST_DEFAULTS["PERIOD_LABEL"],
            usage_start="2026-07-01",
            usage_end="2026-07-31",
        ),
        royalty_admin_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_PERIOD_LABEL.value, 409)

    unchanged = validate_success(
        api.get_period(incumbent["id"], royalty_admin_headers), 200
    )
    assert unchanged["usage_start"] == TEST_DEFAULTS["PERIOD_USAGE_START"]
    assert unchanged["usage_end"] == TEST_DEFAULTS["PERIOD_USAGE_END"]
    assert unchanged["version"] == incumbent["version"]


def test_pool_uniqueness_is_on_the_period_territory_tier_triple(
    api, royalty_admin_headers
):
    """A second GB/INDIVIDUAL pool on the same period is refused while a GB/FAMILY pool on that period is created.

    PRD: "The triple of period, territory and tier is unique; a second pool for the same cell is refused with `ERR_DUPLICATE_POOL`."

    Design: Corner/validations/duplicate_natural_keys_are_composite_not_single_column
    """
    period = create_period(api)
    incumbent = validate_success(
        api.create_pool(
            pool_payload(
                period["id"],
                territory_code="GB",
                subscription_tier="INDIVIDUAL",
                subscriber_count=1000,
                gross_revenue_cents=1428570,
            ),
            royalty_admin_headers,
        ),
        201,
    )

    duplicate = api.create_pool(
        pool_payload(
            period["id"],
            territory_code="GB",
            subscription_tier="INDIVIDUAL",
            subscriber_count=5,
            gross_revenue_cents=10,
        ),
        royalty_admin_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_POOL.value, 409)

    pools = validate_success(
        api.list_pools(royalty_admin_headers, params={"period_id": period["id"]}), 200
    )
    assert len(pools) == 1, "the refused duplicate must leave no pool row behind"
    assert pools[0]["id"] == incumbent["id"]
    assert pools[0]["subscriber_count"] == 1000
    assert pools[0]["gross_revenue_cents"] == 1428570

    other_tier = validate_success(
        api.create_pool(
            pool_payload(
                period["id"],
                territory_code="GB",
                subscription_tier="FAMILY",
                subscriber_count=400,
                gross_revenue_cents=900000,
            ),
            royalty_admin_headers,
        ),
        201,
    )
    assert other_tier["territory_code"] == "GB"
    assert other_tier["subscription_tier"] == "FAMILY"


def test_duplicate_statement_refused_while_incumbent_is_draft_and_while_issued(
    api, royalty_admin_headers
):
    """A second statement for the same holder and period is refused both while the incumbent is DRAFT and after it is ISSUED, even though each retry carries a freshly re-read period version.

    PRD: "At most one statement whose `status` is `DRAFT` or `ISSUED` may exist for a given holder and period; a second is refused with `ERR_DUPLICATE_STATEMENT`."

    Design: Corner/validations/duplicate_statement_for_holder_and_period_rejected_in_draft_and_issued
    """
    fixture = setup_all_matched_statement_drafted(api)
    holder_id = fixture["label"]["id"]
    period_id = fixture["period"]["id"]
    assert fixture["statement"]["status"] == "DRAFT"

    while_draft = api.create_statement(
        statement_payload(holder_id, period_id, period_version(api, period_id)),
        royalty_admin_headers,
    )
    validate_error(while_draft, ApiErrorId.ERR_DUPLICATE_STATEMENT.value, 409)

    issued = issue_statement(api, fixture["statement"]["id"])
    assert issued["status"] == "ISSUED"

    while_issued = api.create_statement(
        statement_payload(holder_id, period_id, period_version(api, period_id)),
        royalty_admin_headers,
    )
    validate_error(while_issued, ApiErrorId.ERR_DUPLICATE_STATEMENT.value, 409)

    rows = validate_success(
        api.list_statements(
            royalty_admin_headers,
            params={"rights_holder_id": holder_id, "period_id": period_id},
        ),
        200,
    )
    assert len(rows) == 1, "exactly one statement may exist for the holder and period"
    assert rows[0]["id"] == fixture["statement"]["id"]


# ─────────────────────────────────────────────────────
# Ladder priority 19 — interval well-formedness
# ─────────────────────────────────────────────────────

def test_registration_interval_is_half_open_so_equal_endpoints_are_invalid(
    api, royalty_admin_headers
):
    """A registration whose effective_to equals its effective_from is refused, while the same claim with effective_to one day later is created.

    PRD: "A `RightsRegistration`'s ownership interval runs from `effective_from` inclusive to `effective_to` **exclusive**; equal endpoints would describe an empty interval and are therefore invalid, so `effective_to` must be strictly after `effective_from`."

    Design: Corner/validations/interval_wellformedness_differs_by_entity_half_open_versus_closed
    """
    label = create_label(api)
    recording = create_recording(api)
    holder_headers = make_rights_holder_user_headers(label["id"])

    degenerate = api.create_rights_registration(
        rights_registration_payload(
            recording["id"],
            label["id"],
            work_version(api, recording["id"]),
            territory_set=["GB"],
            effective_from="2026-06-01",
            effective_to="2026-06-01",
        ),
        holder_headers,
    )
    validate_error(degenerate, ApiErrorId.ERR_INVALID_EFFECTIVE_PERIOD.value, 422)

    rows = validate_success(
        api.list_rights_registrations(
            royalty_admin_headers, params={"work_id": recording["id"]}
        ),
        200,
    )
    assert rows == [], "the refused filing must leave no registration row behind"
    unchanged = validate_success(
        api.get_work(recording["id"], royalty_admin_headers), 200
    )
    assert unchanged["version"] == recording["version"]
    assert unchanged["rights_state"] == "UNMATCHED"

    accepted = validate_success(
        api.create_rights_registration(
            rights_registration_payload(
                recording["id"],
                label["id"],
                work_version(api, recording["id"]),
                territory_set=["GB"],
                effective_from="2026-06-01",
                effective_to="2026-06-02",
            ),
            holder_headers,
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["effective_from"] == "2026-06-01"
    assert accepted["effective_to"] == "2026-06-02"


def test_rate_schedule_window_is_closed_so_equal_endpoints_are_legal(
    api, regulatory_officer_headers
):
    """A rate schedule whose effective_to equals its effective_from is accepted as a one-day window, while one whose effective_to precedes its effective_from is refused.

    PRD: "An inverted window — `effective_to` earlier than `effective_from`, remembering that the schedule window is closed at both ends so equal endpoints are legal — is refused with `ERR_INVALID_EFFECTIVE_PERIOD`."

    Design: Corner/validations/interval_wellformedness_differs_by_entity_half_open_versus_closed
    """
    one_day = validate_success(
        api.create_rate_schedule(
            rate_schedule_payload(
                proceeding_ref="CRB-2026-ONEDAY",
                territory_code="GB",
                subscription_tier="STUDENT",
                effective_from="2026-06-01",
                effective_to="2026-06-01",
            ),
            regulatory_officer_headers,
        ),
        201,
    )
    assert one_day["status"] == "PROPOSED"
    assert one_day["effective_from"] == "2026-06-01"
    assert one_day["effective_to"] == "2026-06-01"

    backward = api.create_rate_schedule(
        rate_schedule_payload(
            proceeding_ref="CRB-2026-BACKWARD",
            territory_code="GB",
            subscription_tier="STUDENT",
            effective_from="2026-06-02",
            effective_to="2026-06-01",
        ),
        regulatory_officer_headers,
    )
    validate_error(backward, ApiErrorId.ERR_INVALID_EFFECTIVE_PERIOD.value, 422)


def test_period_usage_window_requires_end_on_or_after_start(api, royalty_admin_headers):
    """A period whose usage_end precedes its usage_start is refused, while a single-day period is accepted and closes its claim window 60 days after usage_end.

    PRD: "`usage_end` must be on or after `usage_start`; an inverted range is refused with `ERR_INVALID_EFFECTIVE_PERIOD`."

    Design: Corner/validations/interval_wellformedness_differs_by_entity_half_open_versus_closed
    """
    inverted = api.create_period(
        period_payload(
            label=TEST_DEFAULTS["PERIOD_LABEL"],
            usage_start="2026-06-30",
            usage_end="2026-06-01",
        ),
        royalty_admin_headers,
    )
    validate_error(inverted, ApiErrorId.ERR_INVALID_EFFECTIVE_PERIOD.value, 422)

    single_day = validate_success(
        api.create_period(
            period_payload(
                label="2026-06-DAY",
                usage_start="2026-06-01",
                usage_end="2026-06-01",
            ),
            royalty_admin_headers,
        ),
        201,
    )
    assert single_day["status"] == "OPEN"
    assert single_day["claim_window_closes_at"] == "2026-07-31T00:00:00.000Z"


# ─────────────────────────────────────────────────────
# Ladder priority 21 — right, work and claimant agreement
# ─────────────────────────────────────────────────────

def test_right_type_must_agree_with_both_work_type_and_holder_type(
    api, royalty_admin_headers
):
    """Each half of the right-type agreement is enforced on its own: a wrong work_type and a wrong claimant holder_type are both refused with ERR_RIGHT_TYPE_WORK_MISMATCH.

    PRD: "The claimant must be entitled to the right it claims: a `MASTER` claim requires the work's `work_type` to be `RECORDING` and the claimant's `holder_type` to be `LABEL` or `DISTRIBUTOR`, while a `MECHANICAL` or `PERFORMANCE` claim requires the work's `work_type` to be `COMPOSITION` and the claimant's `holder_type` to be `PUBLISHER` or `COLLECTIVE`; any other combination is refused with `ERR_RIGHT_TYPE_WORK_MISMATCH`."

    Design: Corner/validations/right_type_must_agree_with_both_work_type_and_holder_type
    """
    label = create_label(api)
    publisher = create_publisher(api, legal_name="Tidewater Songs", rate_bps=1000)
    recording = create_recording(api)
    composition = create_composition(
        api, identifier="T9001234567", title=TEST_DEFAULTS["RECORDING_A_TITLE"]
    )
    label_headers = make_rights_holder_user_headers(label["id"])
    publisher_headers = make_rights_holder_user_headers(publisher["id"])

    def file(work, claimant, headers, right_type):
        return api.create_rights_registration(
            rights_registration_payload(
                work["id"],
                claimant["id"],
                work_version(api, work["id"]),
                right_type=right_type,
                routing="DIRECT",
                share_bps=10000,
                territory_set=["GB"],
                effective_from="2026-01-01",
                effective_to="2027-01-01",
            ),
            headers,
        )

    master_on_composition = file(composition, label, label_headers, "MASTER")
    validate_error(
        master_on_composition, ApiErrorId.ERR_RIGHT_TYPE_WORK_MISMATCH.value, 422
    )

    mechanical_on_recording = file(recording, publisher, publisher_headers, "MECHANICAL")
    validate_error(
        mechanical_on_recording, ApiErrorId.ERR_RIGHT_TYPE_WORK_MISMATCH.value, 422
    )

    master_by_publisher = file(recording, publisher, publisher_headers, "MASTER")
    validate_error(
        master_by_publisher, ApiErrorId.ERR_RIGHT_TYPE_WORK_MISMATCH.value, 422
    )

    performance_by_label = file(composition, label, label_headers, "PERFORMANCE")
    validate_error(
        performance_by_label, ApiErrorId.ERR_RIGHT_TYPE_WORK_MISMATCH.value, 422
    )

    rows = validate_success(api.list_rights_registrations(royalty_admin_headers), 200)
    assert rows == [], "no refused filing may leave a registration row behind"

    good_master = validate_success(file(recording, label, label_headers, "MASTER"), 201)
    assert good_master["status"] == "SUBMITTED"
    assert good_master["right_type"] == "MASTER"

    good_mechanical = validate_success(
        file(composition, publisher, publisher_headers, "MECHANICAL"), 201
    )
    assert good_mechanical["status"] == "SUBMITTED"
    assert good_mechanical["right_type"] == "MECHANICAL"


# ─────────────────────────────────────────────────────
# Ladder priority 20 — routing viability
# ─────────────────────────────────────────────────────

def test_routing_viability_inspects_the_claimant_rate_or_the_named_collective(
    api, royalty_admin_headers
):
    """A DIRECT claim by a holder with a null direct_deal_rate_bps and a COLLECTIVE claim naming a LABEL are both refused with ERR_COLLECTIVE_NOT_ELIGIBLE, while the viable forms are created with the payee the routing dictates.

    PRD: "Routing must be viable: when `routing` is `COLLECTIVE`, the `collective_id` must reference a holder whose `holder_type` is `COLLECTIVE` and whose `home_territory_code` is either `WORLD` or a member of the registration's `territory_set`, and when `routing` is `DIRECT`, the claimant's `direct_deal_rate_bps` must not be null — otherwise `ERR_COLLECTIVE_NOT_ELIGIBLE`."

    Design: Corner/validations/direct_routing_requires_a_claimant_rate_and_collective_requires_a_collective
    """
    rate_free_label = create_holder(
        api,
        legal_name="Ratefree Records",
        holder_type="LABEL",
        home_territory_code="GB",
    )
    assert rate_free_label["direct_deal_rate_bps"] is None

    label = create_label(api)
    publisher = create_publisher(api, legal_name="Tidewater Songs", rate_bps=1000)
    collective = create_collective(
        api, legal_name="Global Mechanical Collective", territory="WORLD"
    )
    recording = create_recording(api)
    composition = create_composition(
        api, identifier="T9001234567", title=TEST_DEFAULTS["RECORDING_A_TITLE"]
    )

    direct_without_rate = api.create_rights_registration(
        rights_registration_payload(
            recording["id"],
            rate_free_label["id"],
            work_version(api, recording["id"]),
            right_type="MASTER",
            routing="DIRECT",
            share_bps=10000,
            territory_set=["GB"],
        ),
        make_rights_holder_user_headers(rate_free_label["id"]),
    )
    validate_error(
        direct_without_rate, ApiErrorId.ERR_COLLECTIVE_NOT_ELIGIBLE.value, 422
    )

    collective_pointing_at_label = api.create_rights_registration(
        rights_registration_payload(
            composition["id"],
            publisher["id"],
            work_version(api, composition["id"]),
            right_type="MECHANICAL",
            routing="COLLECTIVE",
            collective_id=label["id"],
            share_bps=10000,
            territory_set=["GB"],
        ),
        make_rights_holder_user_headers(publisher["id"]),
    )
    validate_error(
        collective_pointing_at_label, ApiErrorId.ERR_COLLECTIVE_NOT_ELIGIBLE.value, 422
    )

    rows = validate_success(api.list_rights_registrations(royalty_admin_headers), 200)
    assert rows == [], "no refused filing may leave a registration row behind"

    through_collective = validate_success(
        api.create_rights_registration(
            rights_registration_payload(
                composition["id"],
                publisher["id"],
                work_version(api, composition["id"]),
                right_type="MECHANICAL",
                routing="COLLECTIVE",
                collective_id=collective["id"],
                share_bps=10000,
                territory_set=["GB"],
            ),
            make_rights_holder_user_headers(publisher["id"]),
        ),
        201,
    )
    assert through_collective["payee_holder_id"] == collective["id"]

    direct_with_rate = validate_success(
        api.create_rights_registration(
            rights_registration_payload(
                recording["id"],
                label["id"],
                work_version(api, recording["id"]),
                right_type="MASTER",
                routing="DIRECT",
                share_bps=10000,
                territory_set=["GB"],
            ),
            make_rights_holder_user_headers(label["id"]),
        ),
        201,
    )
    assert direct_with_rate["payee_holder_id"] == label["id"]


# ─────────────────────────────────────────────────────
# Ladder priority 24 — publishing split
# ─────────────────────────────────────────────────────

def test_publishing_split_must_sum_to_exactly_10000(api, regulatory_officer_headers):
    """A rate schedule whose mechanical and performance shares sum to anything other than 10,000 is refused, while a zero mechanical share summing to 10,000 is accepted.

    PRD: "The publishing split must be exhaustive: `mechanical_share_bps` and `performance_share_bps` must sum to exactly 10,000, and a proposal that fails this is refused with `ERR_RATE_SHARE_SPLIT_INVALID`."

    Design: Corner/validations/rate_schedule_publishing_split_must_total_10000
    """
    under = api.create_rate_schedule(
        rate_schedule_payload(
            proceeding_ref="CRB-2026-LOW",
            mechanical_share_bps=4000,
            performance_share_bps=5000,
        ),
        regulatory_officer_headers,
    )
    validate_error(under, ApiErrorId.ERR_RATE_SHARE_SPLIT_INVALID.value, 422)

    over = api.create_rate_schedule(
        rate_schedule_payload(
            proceeding_ref="CRB-2026-HIGH",
            mechanical_share_bps=4001,
            performance_share_bps=6000,
        ),
        regulatory_officer_headers,
    )
    validate_error(over, ApiErrorId.ERR_RATE_SHARE_SPLIT_INVALID.value, 422)

    all_performance = validate_success(
        api.create_rate_schedule(
            rate_schedule_payload(
                proceeding_ref="CRB-2026-ALLPERF",
                mechanical_share_bps=0,
                performance_share_bps=10000,
            ),
            regulatory_officer_headers,
        ),
        201,
    )
    assert all_performance["status"] == "PROPOSED"
    assert all_performance["mechanical_share_bps"] == 0
    assert all_performance["performance_share_bps"] == 10000


# ─────────────────────────────────────────────────────
# Ladder priority 25 — non-degenerate usage
# ─────────────────────────────────────────────────────

def test_seal_refuses_a_batch_carrying_no_lines(api, rights_ops_analyst_headers):
    """Sealing a batch whose line_count is 0 is refused and leaves the batch OPEN, and the same seal call succeeds once one line exists.

    PRD: "A seal attempted on a batch with no lines at all is refused with `ERR_EMPTY_USAGE_BATCH`, because an empty batch would otherwise let a period be sealed with no usage in it."

    Design: Corner/validations/empty_batch_cannot_seal_and_zero_play_line_cannot_exist
    """
    period = create_period(api)
    batch = create_batch(api, period["id"])
    assert batch["line_count"] == 0

    refused = api.seal_usage_batch(batch["id"], rights_ops_analyst_headers)
    validate_error(refused, ApiErrorId.ERR_EMPTY_USAGE_BATCH.value, 422)

    still_open = validate_success(
        api.get_usage_batch(batch["id"], rights_ops_analyst_headers), 200
    )
    assert still_open["status"] == "OPEN"
    assert still_open["line_count"] == 0
    assert still_open["version"] == batch["version"]

    append_line(api, batch["id"], play_count=1)
    sealed = validate_success(
        api.seal_usage_batch(batch["id"], rights_ops_analyst_headers), 200
    )
    assert sealed["status"] == "SEALED"
    assert sealed["line_count"] == 1
    assert sealed["total_play_count"] == 1


def test_usage_line_append_refuses_a_play_count_below_one(
    api, rights_ops_analyst_headers
):
    """A usage line offered with play_count 0 is refused and leaves the batch empty, while a single-play line is accepted.

    PRD: "A line offered with a `play_count` below 1 is refused with `ERR_ZERO_PLAY_COUNT`."

    Design: Corner/validations/empty_batch_cannot_seal_and_zero_play_line_cannot_exist
    """
    period = create_period(api)
    batch = create_batch(api, period["id"])

    refused = api.append_usage_line(
        batch["id"],
        usage_line_payload(
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            territory_code="GB",
            subscription_tier="INDIVIDUAL",
            play_count=0,
        ),
        rights_ops_analyst_headers,
    )
    validate_error(refused, ApiErrorId.ERR_ZERO_PLAY_COUNT.value, 422)

    unchanged = validate_success(
        api.get_usage_batch(batch["id"], rights_ops_analyst_headers), 200
    )
    assert unchanged["line_count"] == 0
    assert unchanged["total_play_count"] == 0
    assert unchanged["version"] == batch["version"]
    lines = validate_success(
        api.list_usage_lines(
            rights_ops_analyst_headers, params={"batch_id": batch["id"]}
        ),
        200,
    )
    assert lines == [], "the refused append must leave no usage line behind"

    accepted = validate_success(
        api.append_usage_line(
            batch["id"],
            usage_line_payload(
                reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
                territory_code="GB",
                subscription_tier="INDIVIDUAL",
                play_count=1,
            ),
            rights_ops_analyst_headers,
        ),
        201,
    )
    assert accepted["play_count"] == 1
    assert accepted["match_status"] == "UNMATCHED"


# ─────────────────────────────────────────────────────
# Ladder priority 33 — open ownership claims
# ─────────────────────────────────────────────────────

def test_open_claims_block_period_close_until_every_claim_is_terminal(
    api, royalty_admin_headers
):
    """A period close is refused with ERR_UNRESOLVED_REGISTRATIONS while a rival claim sits in SUBMITTED and still while it sits in UNDER_REVIEW, and succeeds once that claim is REJECTED.

    PRD: "And no registration touching a work that carries usage in this period may still be in `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_EVIDENCE` or `DISPUTED` status; an open claim is refused with `ERR_UNRESOLVED_REGISTRATIONS`."

    Design: Corner/validations/open_claims_block_period_close_until_every_claim_is_terminal
    """
    fixture = _setup_distributed_period_with_open_rival_claim(api)
    period_id = fixture["period"]["id"]
    rival_registration_id = fixture["rival_registration"]["id"]
    assert fixture["rival_registration"]["status"] == "SUBMITTED"

    before = validate_success(api.get_period(period_id, royalty_admin_headers), 200)
    assert before["status"] == "DISTRIBUTED"
    assert before["total_holding_cents"] == 0
    assert before["claim_window_closes_at"] == TEST_DEFAULTS[
        "PERIOD_CLAIM_WINDOW_CLOSES_AT"
    ]

    while_submitted = api.close_period(period_id, royalty_admin_headers)
    validate_error(
        while_submitted, ApiErrorId.ERR_UNRESOLVED_REGISTRATIONS.value, 422
    )
    assert (
        validate_success(api.get_period(period_id, royalty_admin_headers), 200)["status"]
        == "DISTRIBUTED"
    )

    under_review = review_registration(api, rival_registration_id)
    assert under_review["status"] == "UNDER_REVIEW"

    while_under_review = api.close_period(period_id, royalty_admin_headers)
    validate_error(
        while_under_review, ApiErrorId.ERR_UNRESOLVED_REGISTRATIONS.value, 422
    )
    assert (
        validate_success(api.get_period(period_id, royalty_admin_headers), 200)["status"]
        == "DISTRIBUTED"
    )

    rejected = reject_registration(
        api, rival_registration_id, rejection_reason="no chain of title produced"
    )
    assert rejected["status"] == "REJECTED"

    closed = validate_success(api.close_period(period_id, royalty_admin_headers), 200)
    assert closed["status"] == "CLOSED"
