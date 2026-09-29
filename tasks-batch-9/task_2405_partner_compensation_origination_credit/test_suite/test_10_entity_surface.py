"""Entity surface: declared fields and defaults on creation, server-minted
system fields, schema rejection, immutability of the cash ledger, body foreign
keys, list paging and the role-qualified credit-allocation junction."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    approx2,
    approx4,
    assert_contribution_record,
    assert_credit_allocation,
    assert_cycle,
    assert_draw_payment,
    assert_partner,
    advance_cycle,
    create_contribution_record_payload,
    create_cycle,
    create_cycle_payload,
    create_matter,
    create_matter_payload,
    create_partner,
    create_partner_payload,
    create_peer_review_payload,
    find_allocation,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_cycle_admin_headers,
    matter_allocations,
    partner_allocations,
    read_matter,
    read_partner,
    setup_drawn_award,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_cycle_returns_declared_fields_and_pool_defaults(api):
    """PRD 3.8: "The cycle carries the year's cash parameters:
    `distributable_pool_cents`, the total the firm will distribute, and
    `lockstep_unit_cents`, the cash value of one lockstep rung, both integers of
    at least 0; `discretionary_pool_pct`, the fraction of the distributable pool
    reserved for discretionary partners, between 0.0000 and 1.0000 at 4 decimal
    places and defaulting to 0.20; and `draw_pct`, the fraction of a target award
    paid out as monthly draws before true-up, on the same scale and defaulting to
    0.80." "The cycle is created in `OPEN_INTAKE` with every computed pool field
    at 0, `haircut_applied_pct` at 0.0000, `reopen_count` at 0 and
    `confidentiality_locked` false, and creation returns 201 Created."

    Design: Corner/entities/create_cycle_returns_declared_fields_and_pool_defaults
    """
    payload = create_cycle_payload(
        fiscal_year=2026,
        distributable_pool_cents=100_000_000,
        lockstep_unit_cents=5_000_000,
        claim_deadline_on="2026-09-30",
        assessment_deadline_on="2026-10-31",
    )
    payload.pop("discretionary_pool_pct")
    payload.pop("draw_pct")

    response = api.create_cycle(payload, make_cycle_admin_headers())
    data = validate_success(response, 201)
    body = response.json()

    assert_cycle(data)
    assert data["discretionary_pool_pct"] == approx4(0.2000)
    assert data["draw_pct"] == approx4(0.8000)
    assert data["state"] == "OPEN_INTAKE"
    assert data["lockstep_reserved_cents"] == 0
    assert data["discretionary_pool_cents"] == 0
    assert data["formula_pool_cents"] == 0
    assert data["haircut_applied_pct"] == approx4(0.0000)
    assert data["total_formula_score"] == approx4(0.0000)
    assert data["total_committee_points"] == approx2(0.00)
    assert data["unsettled_award_count"] == 0
    assert data["reopen_count"] == 0
    assert data["confidentiality_locked"] is False
    assert data["version"] == 1

    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_partner_boolean_and_capital_defaults_applied_when_omitted(api):
    """PRD 3.1: "Four optional flags shape how the partner participates:
    `lockstep_step` (an integer rung from 0 through 12, defaulting to 0),
    `is_committee_member` and `is_credit_arbiter` (both defaulting to false), and
    `evaluation_required` (defaulting to true, and set to false for the
    committee-only senior partners who vote but are not themselves scored this
    year)." "Newly admitted partners begin with `status` of `ACTIVE` and
    `departure_effective_on` null, and their `capital_account_balance_cents` is
    seeded to exactly the `opening_capital_cents` supplied."

    Design: Corner/entities/partner_boolean_and_capital_defaults_applied_when_omitted
    """
    defaulted = validate_success(
        api.create_partner(
            create_partner_payload(
                full_name="Dee Fault",
                practice_group="TAX",
                compensation_model="FORMULA",
                admission_year=2016,
            ),
            make_cycle_admin_headers(),
        ),
        201,
    )
    seeded = validate_success(
        api.create_partner(
            create_partner_payload(
                full_name="Cap Seeded",
                practice_group="TAX",
                compensation_model="FORMULA",
                admission_year=2016,
                opening_capital_cents=4_500_000,
                target_capital_cents=9_000_000,
            ),
            make_cycle_admin_headers(),
        ),
        201,
    )

    assert_partner(defaulted)
    assert defaulted["evaluation_required"] is True
    assert defaulted["is_committee_member"] is False
    assert defaulted["is_credit_arbiter"] is False
    assert defaulted["lockstep_step"] == 0
    assert defaulted["opening_capital_cents"] == 0
    assert defaulted["target_capital_cents"] == 0
    assert defaulted["capital_account_balance_cents"] == 0
    assert defaulted["status"] == "ACTIVE"
    assert defaulted["departure_effective_on"] is None

    assert seeded["capital_account_balance_cents"] == 4_500_000
    assert seeded["opening_capital_cents"] == 4_500_000
    assert seeded["target_capital_cents"] == 9_000_000


def test_create_matter_missing_responsible_attorney_is_rejected(api):
    """PRD 3.2: "A matter is opened by a `CycleAdmin` with a `client_key` of 1 to
    64 characters — compared case-sensitively, and shared verbatim by every matter
    belonging to the same client — a human-readable `client_display_name`, a
    `matter_type` of `NEW_CLIENT`, `EXPANDED_MATTER`, `CROSS_SELL` or `EXISTING`,
    a `practice_group` drawn from the same five groups partners belong to, an
    `opened_on` calendar date, and the two attorney assignments
    `billing_attorney_id` and `responsible_attorney_id`." PRD 2.9: "Conversely, a
    rejected request changes nothing: every field named by a failed operation
    keeps the value it had before the call."

    Design: Corner/entities/create_matter_missing_responsible_attorney_is_rejected
    """
    billing = create_partner(
        api, full_name="Ada Origin", practice_group="CORPORATE", admission_year=2010
    )
    payload = create_matter_payload(
        client_key="CLI-M1",
        client_display_name="Missing Fields Inc",
        matter_type="EXISTING",
        practice_group="CORPORATE",
        opened_on="2026-01-10",
        billing_attorney_id=billing["id"],
    )
    assert "responsible_attorney_id" not in payload

    response = api.create_matter(payload, make_cycle_admin_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    rows, meta = validate_paginated(
        api.list_matters(make_cycle_admin_headers(), {"client_key": "CLI-M1"})
    )
    assert rows == []
    assert meta["total_count"] == 0

    assert read_partner(api, billing["id"])["responsible_matter_count"] == 0
    allocations, alloc_meta = validate_paginated(
        api.list_partner_credit_allocations(billing["id"], make_cycle_admin_headers())
    )
    assert allocations == []
    assert alloc_meta["total_count"] == 0


def test_contribution_record_standard_value_is_computed_not_input(api):
    """PRD 3.3: "Creation returns 201 Created, sets `standard_value_cents` to
    `hours` multiplied by `standard_rate_cents` rounded half up for billable rows
    and to 0 for non-billable rows, and leaves `verified` false with `verified_at`
    null." "`matter_id` is required when `kind` is `BILLABLE` and must be omitted
    entirely when `kind` is `NON_BILLABLE`; `standard_rate_cents` must be greater
    than 0 when `kind` is `BILLABLE` and must be either 0 or omitted otherwise,
    defaulting to 0."

    Design: Corner/entities/contribution_record_standard_value_is_computed_not_input
    """
    cycle = create_cycle(api)
    partner = create_partner(
        api, full_name="Cal Compute", practice_group="IP", admission_year=2016
    )
    matter = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-CV",
        client_display_name="Computed Value Ltd",
        matter_type="EXISTING",
        practice_group="IP",
        opened_on="2026-01-10",
    )

    billable = validate_success(
        api.create_contribution_record(
            create_contribution_record_payload(
                partner_id=partner["id"],
                cycle_id=cycle["id"],
                matter_id=matter["id"],
                kind="BILLABLE",
                category="CLIENT_WORK",
                hours=12.50,
                standard_rate_cents=48000,
                service_period_start="2026-02-01",
                service_period_end="2026-02-28",
            ),
            make_cycle_admin_headers(),
        ),
        201,
    )

    non_billable_payload = create_contribution_record_payload(
        partner_id=partner["id"],
        cycle_id=cycle["id"],
        kind="NON_BILLABLE",
        category="RECRUITING",
        hours=12.50,
        service_period_start="2026-03-01",
        service_period_end="2026-03-31",
    )
    non_billable_payload.pop("standard_rate_cents")
    non_billable = validate_success(
        api.create_contribution_record(non_billable_payload, make_cycle_admin_headers()),
        201,
    )

    assert_contribution_record(billable)
    assert_contribution_record(non_billable)
    assert billable["standard_value_cents"] == 600_000
    assert billable["verified"] is False
    assert billable["verified_at"] is None

    assert non_billable["standard_rate_cents"] == 0
    assert non_billable["standard_value_cents"] == 0
    assert non_billable["matter_id"] is None
    assert non_billable["verified"] is False
    assert non_billable["verified_at"] is None

    assert read_partner(api, partner["id"])["verified_billable_hours"] == approx2(0.00)
    assert read_partner(api, partner["id"])["non_billable_points"] == approx2(0.00)
    assert read_matter(api, matter["id"])["verified_billable_hours"] == approx2(0.00)


def test_partner_system_fields_generated_and_version_starts_at_one(api):
    """PRD 2.4: "Almost every resource additionally carries `updated_at`, an ISO
    8601 UTC timestamp refreshed on every change to the resource, and `version`,
    an integer that starts at 1 on creation and increments by exactly 1 on every
    mutation." PRD 3.1: "Newly admitted partners begin with `status` of `ACTIVE`
    and `departure_effective_on` null, and their `capital_account_balance_cents`
    is seeded to exactly the `opening_capital_cents` supplied."

    Design: Corner/entities/partner_system_fields_generated_and_version_starts_at_one
    """
    payload = create_partner_payload(
        full_name="Sys Field",
        practice_group="LITIGATION",
        compensation_model="DISCRETIONARY",
        admission_year=2017,
    )

    data = validate_success(api.create_partner(payload, make_cycle_admin_headers()), 201)

    assert_partner(data)
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert data["id"] not in payload.values()
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["created_at"].startswith("2026-08-01T00:00:00")
    assert data["updated_at"] == data["created_at"]
    assert data["status"] == "ACTIVE"
    assert data["departure_effective_on"] is None

    stored = read_partner(api, data["id"])
    assert stored == data


def test_invalid_enum_and_out_of_range_values_are_rejected(api):
    """PRD 3.1: "The lockstep rung and the compensation model are cross-checked at
    admission and on every later edit of either: a partner whose
    `compensation_model` is `LOCKSTEP` must carry a `lockstep_step` of at least 1,
    and a partner on either other model must carry a `lockstep_step` of exactly
    0." "A violation of either half of that rule is a malformed request and is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/invalid_enum_and_out_of_range_values_are_rejected
    """
    admin = make_cycle_admin_headers()

    validate_error(
        api.create_partner(
            create_partner_payload(
                full_name="Bad Group",
                practice_group="MARITIME",
                compensation_model="FORMULA",
                admission_year=2016,
            ),
            admin,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api.create_partner(
            create_partner_payload(
                full_name="Bad Step",
                practice_group="TAX",
                compensation_model="LOCKSTEP",
                admission_year=2016,
                lockstep_step=0,
            ),
            admin,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api.create_partner(
            create_partner_payload(
                full_name="Bad Step Two",
                practice_group="TAX",
                compensation_model="FORMULA",
                admission_year=2016,
                lockstep_step=4,
            ),
            admin,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api.create_cycle(
            create_cycle_payload(discretionary_pool_pct=1.5000),
            admin,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    accepted = validate_success(
        api.create_partner(
            create_partner_payload(
                full_name="Good Step",
                practice_group="TAX",
                compensation_model="LOCKSTEP",
                admission_year=2016,
                lockstep_step=4,
            ),
            admin,
        ),
        201,
    )

    partners, partner_meta = validate_paginated(api.list_partners(admin))
    assert len(partners) == 1
    assert partner_meta["total_count"] == 1
    assert partners[0]["id"] == accepted["id"]
    assert accepted["lockstep_step"] == 4
    assert accepted["compensation_model"] == "LOCKSTEP"

    cycles, cycle_meta = validate_paginated(api.list_cycles(admin))
    assert cycles == []
    assert cycle_meta["total_count"] == 0


def test_draw_payment_is_immutable_and_carries_no_version_field(api):
    """PRD 2.4: "The one exception is the cash ledger." "A draw-payment row is
    append-only and immutable: it carries `id` and `created_at` and nothing else
    of that family — it has no `updated_at` field and no `version` field at all,
    and there is no endpoint that edits one."

    Design: Corner/entities/draw_payment_is_immutable_and_carries_no_version_field
    """
    bundle = setup_drawn_award(api, periods=((2026, 1),), points=(800.00, 600.00))
    award = bundle["award"]

    rows, meta = validate_paginated(
        api.list_draw_payments(award["id"], make_cycle_admin_headers(), {"kind": "SCHEDULED_DRAW"})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["amount_cents"] == 1_333_333
    assert rows[0]["reversed"] is False

    payment = validate_success(
        api.get_draw_payment(rows[0]["id"], make_cycle_admin_headers()), 200
    )
    assert_draw_payment(payment)
    assert payment["id"] == rows[0]["id"]
    assert payment["kind"] == "SCHEDULED_DRAW"
    assert payment["period_year"] == 2026
    assert payment["period_month"] == 1
    assert payment["award_id"] == award["id"]
    assert "version" not in payment
    assert "updated_at" not in payment


def test_peer_review_requires_an_existing_self_assessment_parent(api):
    """PRD 2.10: "Foreign keys supplied inside a request body are resolved after
    the path and are checked in the order in which the endpoint declares its input
    fields, again returning the not-found code of the first unresolvable
    reference." "This applies to matter creation, contribution-record creation,
    claim creation, self-assessment creation, peer-review assignment and
    credit-transition effectuation, and the codes reachable this way are
    `ERR_CYCLE_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`, `ERR_MATTER_NOT_FOUND` and
    `ERR_ASSESSMENT_NOT_FOUND`."

    Design: Corner/entities/peer_review_requires_an_existing_self_assessment_parent
    """
    cycle = create_cycle(api)
    reviewer = create_partner(
        api,
        full_name="Rita Reviewer",
        practice_group="TAX",
        admission_year=2009,
        evaluation_required=False,
    )
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")

    response = api.create_peer_review(
        create_peer_review_payload(UNKNOWN_UUID, reviewer["id"]), make_cycle_admin_headers()
    )
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value, 404)

    rows, meta = validate_paginated(api.list_peer_reviews(make_cycle_admin_headers()))
    assert rows == []
    assert meta["total_count"] == 0


def test_list_partners_pagination_filtering_and_ordering(api):
    """PRD 2.3: "`limit` caps the number of rows returned; it defaults to 10, its
    minimum accepted value is 1 and its maximum is 100." "Every list response
    repeats `limit` and `offset` in the envelope's `meta` object alongside
    `total_count`, the number of rows matching the filter before paging, and
    `has_more`, a boolean that is true when rows remain beyond the current page."
    "Unless a specific list states otherwise, rows are ordered by `created_at`
    ascending."

    Design: Corner/entities/list_partners_pagination_filtering_and_ordering
    """
    admin = make_cycle_admin_headers()
    first = create_partner(
        api, full_name="P One", practice_group="LITIGATION", compensation_model="FORMULA", admission_year=2010
    )
    second = create_partner(
        api, full_name="P Two", practice_group="CORPORATE", compensation_model="DISCRETIONARY", admission_year=2011
    )
    third = create_partner(
        api,
        full_name="P Three",
        practice_group="TAX",
        compensation_model="LOCKSTEP",
        admission_year=2012,
        lockstep_step=3,
    )
    fourth = create_partner(
        api, full_name="P Four", practice_group="IP", compensation_model="FORMULA", admission_year=2013
    )

    paged_response = api.list_partners(admin, {"limit": 2, "offset": 1})
    paged, paged_meta = validate_paginated(paged_response)
    assert [row["id"] for row in paged] == [second["id"], third["id"]]
    assert paged_meta["total_count"] == 4
    assert paged_meta["has_more"] is True
    assert paged_meta["limit"] == 2
    assert paged_meta["offset"] == 1
    assert paged_response.json()["response_type"] == "array"

    filtered_response = api.list_partners(admin, {"compensation_model": "DISCRETIONARY"})
    filtered, filtered_meta = validate_paginated(filtered_response)
    assert [row["id"] for row in filtered] == [second["id"]]
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert filtered_response.json()["response_type"] == "array"

    defaulted, defaulted_meta = validate_paginated(api.list_partners(admin))
    assert [row["id"] for row in defaulted] == [
        first["id"],
        second["id"],
        third["id"],
        fourth["id"],
    ]
    assert defaulted_meta["limit"] == 10
    assert defaulted_meta["offset"] == 0
    assert defaulted_meta["has_more"] is False


def test_get_partner_returns_the_stored_row_unchanged(api):
    """PRD 2.4: "Every resource the service persists carries a server-minted `id`,
    formatted as a UUID with no type prefix, and a `created_at` timestamp rendered
    as an ISO 8601 UTC instant with three fractional digits." PRD 3.1: "Two
    optional capital figures complete the record: `opening_capital_cents`, the
    balance carried into the cycle, and `target_capital_cents`, the balance the
    partnership agreement requires — both are integers of at least 0 and both
    default to 0."

    Design: Corner/entities/get_partner_returns_the_stored_row_unchanged
    """
    created = validate_success(
        api.create_partner(
            create_partner_payload(
                full_name="Ren Read",
                practice_group="REGULATORY",
                compensation_model="LOCKSTEP",
                admission_year=2003,
                lockstep_step=7,
                is_committee_member=True,
                is_credit_arbiter=True,
                evaluation_required=True,
                opening_capital_cents=1_000_000,
                target_capital_cents=5_000_000,
            ),
            make_cycle_admin_headers(),
        ),
        201,
    )

    read_back = validate_success(
        api.get_partner(created["id"], make_cycle_admin_headers()), 200
    )

    assert read_back["id"] == created["id"]
    assert read_back["version"] == created["version"] == 1
    assert read_back["full_name"] == "Ren Read"
    assert read_back["practice_group"] == "REGULATORY"
    assert read_back["compensation_model"] == "LOCKSTEP"
    assert read_back["admission_year"] == 2003
    assert read_back["lockstep_step"] == 7
    assert read_back["is_committee_member"] is True
    assert read_back["is_credit_arbiter"] is True
    assert read_back["evaluation_required"] is True
    assert read_back["opening_capital_cents"] == 1_000_000
    assert read_back["capital_account_balance_cents"] == 1_000_000
    assert read_back["target_capital_cents"] == 5_000_000
    assert read_back == created


def test_credit_allocation_junction_carries_role_and_interval_per_partner_matter_pair(api):
    """PRD 3.2: "A `BILLING` allocation is created for the billing attorney and a
    `RESPONSIBLE` allocation for the responsible attorney, each at `credit_pct` of
    100.00, each with `source` of `DEFAULT_BILLING`, `credit_from` equal to the
    matter's `opened_on`, `credit_through` null and `state` of `ACTIVE`."

    Design: Corner/entities/credit_allocation_junction_carries_role_and_interval_per_partner_matter_pair
    """
    admin = make_cycle_admin_headers()
    partner = create_partner(
        api, full_name="Jun Junction", practice_group="CORPORATE", admission_year=2016
    )
    matter = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-JN",
        client_display_name="Junction Joint Ltd",
        matter_type="EXISTING",
        practice_group="CORPORATE",
        opened_on="2026-01-20",
    )

    from_matter, _ = validate_paginated(
        api.list_matter_credit_allocations(matter["id"], admin, {"credit_role": "BILLING"})
    )
    from_partner, _ = validate_paginated(
        api.list_partner_credit_allocations(partner["id"], admin, {"credit_role": "BILLING"})
    )
    assert len(from_matter) == 1
    assert len(from_partner) == 1
    assert from_partner[0]["id"] == from_matter[0]["id"]

    billing = validate_success(
        api.get_credit_allocation(from_matter[0]["id"], admin), 200
    )
    assert_credit_allocation(billing)
    assert billing["credit_role"] == "BILLING"
    assert billing["partner_id"] == partner["id"]
    assert billing["matter_id"] == matter["id"]
    assert billing["credit_pct"] == approx2(100.00)
    assert billing["credit_from"] == "2026-01-20"
    assert billing["credit_through"] is None
    assert billing["source"] == "DEFAULT_BILLING"
    assert billing["state"] == "ACTIVE"

    every_role = matter_allocations(api, matter["id"])
    assert len(every_role) == 2
    responsible = find_allocation(every_role, "RESPONSIBLE", partner["id"])
    assert responsible["id"] != billing["id"]
    assert responsible["credit_pct"] == approx2(100.00)
    assert responsible["source"] == "DEFAULT_BILLING"
    assert responsible["credit_from"] == "2026-01-20"
    assert responsible["credit_through"] is None

    assert matter_allocations(api, matter["id"], credit_role="ORIGINATING") == []
    assert partner_allocations(api, partner["id"], credit_role="ORIGINATING") == []
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 1
