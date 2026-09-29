"""Resource shapes, server-side defaults, system fields and reference resolution.

Every test builds its own state from an empty database through PRD-declared
endpoints, and asserts only values the PRD names explicitly.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_append_only_fields,
    assert_millisecond_timestamp,
    create_active_license,
    create_beam,
    create_beam_payload,
    create_cell,
    create_service_cell_payload,
    create_service_order_payload,
    create_service_plan_payload,
    create_spectrum_license_payload,
    create_subscriber,
    create_subscriber_payload,
    deliver_terminal,
    is_valid_uuid,
    make_subscriber_headers,
    obstruction_scan_payload,
    set_clock,
    ship_terminal,
    validate_error,
    validate_paginated,
    validate_success,
)

EPOCH_EMITTED = "2026-08-01T00:00:00.000Z"


# ───────────────────────── creation and retrieval ────────────────────────

def test_spectrum_license_creation_returns_every_declared_field(api, compliance_headers):
    """Filing a licence echoes every declared input and mints the regulatory dimensions.

    PRD §3.1: "Filing supplies the regulator-issued `license_code`, which must be between 1 and 40 characters and unique across all licences; the `jurisdiction_code` the licence authorises service in, between 2 and 8 characters composed of uppercase letters and a single hyphen, such as `US-CA`, `US-NV` or `CA-BC`; the `frequency_band`, which is one of `KA_FORWARD`, `KU_FORWARD` or `KA_RETURN`; the `max_eirp_dbw` ceiling on authorised effective isotropic radiated power, which must be strictly greater than zero; the `expires_at` instant at which the authorisation lapses; and the `consumer_disclosure_version` string, between 1 and 20 characters, naming the disclosure text the jurisdiction mandates."
    PRD §3.1: "A filed licence lands in `license_state` `PENDING_COORDINATION` with `coordination_state` `UNCOORDINATED`, and with `coordination_note` and `enforcement_reason` both empty."
    PRD §2.5: "Every persisted record exposes an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp recording the logical-clock instant of creation."
    PRD §2.5: "`updated_at` is refreshed to the logical-clock instant of the most recent mutation of that record, and `version` is an integer that starts at 1 when the record is created and increases by exactly 1 on every mutation, including mutations a record suffers as the downstream hop of somebody else's cascade."
    PRD §2.4: "Every timestamp the API emits is formatted as ISO 8601 UTC with exactly three fractional digits, for example `2026-08-01T00:00:00.000Z`."

    Design: Corner/entities/spectrum_license_creation_returns_every_declared_field
    """
    set_clock(CLOCK_EPOCH)

    payload = create_spectrum_license_payload(
        license_code="LIC-US-CA-KA-01",
        jurisdiction_code="US-CA",
        frequency_band="KA_FORWARD",
        max_eirp_dbw=62.5,
        expires_at="2027-12-31T00:00:00Z",
        consumer_disclosure_version="CD-2026.1",
        in_motion_permitted=True,
    )
    data = validate_success(api.create_spectrum_license(payload, compliance_headers), 201)

    assert data["license_code"] == "LIC-US-CA-KA-01", "license_code must echo the filing"
    assert data["jurisdiction_code"] == "US-CA", "jurisdiction_code must echo the filing"
    assert data["frequency_band"] == "KA_FORWARD", "frequency_band must echo the filing"
    assert data["max_eirp_dbw"] == pytest.approx(62.5, abs=0.001), (
        f"max_eirp_dbw must echo 62.5, got {data['max_eirp_dbw']}"
    )
    assert data["expires_at"] == "2027-12-31T00:00:00.000Z", (
        f"expires_at must be emitted with three fractional digits, got {data['expires_at']!r}"
    )
    assert data["consumer_disclosure_version"] == "CD-2026.1", (
        "consumer_disclosure_version must echo the filing"
    )
    assert data["in_motion_permitted"] is True, "in_motion_permitted must echo the filing"

    assert data["license_state"] == "PENDING_COORDINATION", (
        f"a filed licence lands PENDING_COORDINATION, got {data['license_state']}"
    )
    assert data["coordination_state"] == "UNCOORDINATED", (
        f"a filed licence lands UNCOORDINATED, got {data['coordination_state']}"
    )
    assert not data.get("coordination_note"), (
        f"coordination_note starts empty, got {data.get('coordination_note')!r}"
    )
    assert not data.get("enforcement_reason"), (
        f"enforcement_reason starts empty, got {data.get('enforcement_reason')!r}"
    )

    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert data["version"] == 1, f"a newly created record starts at version 1, got {data['version']}"
    assert data["created_at"] == EPOCH_EMITTED, (
        f"created_at must be the logical-clock instant {EPOCH_EMITTED}, got {data['created_at']!r}"
    )
    assert_millisecond_timestamp(data["updated_at"])


def test_beam_retrieval_returns_stored_capacity_fields(api, netops_headers):
    """A read-back of a fresh beam returns its inputs plus the zero-state capacity picture.

    PRD §3.2: "Creating a beam supplies its `beam_code`, between 1 and 40 characters and unique across beams; the `satellite_code` of the spacecraft carrying it; the `spectrum_license_id` of the licence it radiates under; and its physical `forward_capacity_mbps`, which must be strictly greater than zero."
    PRD §3.2: "A freshly created beam starts with `weighted_sold_mbps` at 0, `oversubscription_ratio` at 0, `capacity_state` `NORMAL`, `deprioritization_grace_gb` at 0, `billing_cycle_index` at 0 and no `last_cycle_closed_at` recorded."
    PRD §3.2: "Its `beam_state` is `ACTIVE` when the named licence is `ACTIVE`, and `SUSPENDED` otherwise — a beam created under a licence still in `PENDING_COORDINATION` is born out of service."
    PRD §2.5: "`updated_at` is refreshed to the logical-clock instant of the most recent mutation of that record, and `version` is an integer that starts at 1 when the record is created and increases by exactly 1 on every mutation, including mutations a record suffers as the downstream hop of somebody else's cascade."

    Design: Corner/entities/beam_retrieval_returns_stored_capacity_fields
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_active_license()
    beam = create_beam(
        license_record["id"],
        beam_code="BEAM-01",
        satellite_code="SAT-A",
        forward_capacity_mbps=100,
    )

    data = validate_success(api.get_beam(beam["id"], netops_headers), 200)

    assert data["beam_code"] == "BEAM-01", "beam_code must echo the creation"
    assert data["satellite_code"] == "SAT-A", "satellite_code must echo the creation"
    assert data["spectrum_license_id"] == license_record["id"], (
        "spectrum_license_id must name the licence the beam radiates under"
    )
    assert data["forward_capacity_mbps"] == pytest.approx(100, abs=0.001), (
        f"forward_capacity_mbps must echo 100, got {data['forward_capacity_mbps']}"
    )

    assert data["weighted_sold_mbps"] == pytest.approx(0, abs=0.001), (
        f"a fresh beam has sold nothing, got {data['weighted_sold_mbps']}"
    )
    assert data["oversubscription_ratio"] == pytest.approx(0, abs=0.001), (
        f"a fresh beam's ratio is 0, got {data['oversubscription_ratio']}"
    )
    assert data["capacity_state"] == "NORMAL", (
        f"a fresh beam is NORMAL, got {data['capacity_state']}"
    )
    assert data["deprioritization_grace_gb"] == 0, (
        f"a fresh beam's grace volume is 0, got {data['deprioritization_grace_gb']}"
    )
    assert data["billing_cycle_index"] == 0, (
        f"a fresh beam's billing_cycle_index is 0, got {data['billing_cycle_index']}"
    )
    assert not data.get("last_cycle_closed_at"), (
        f"a fresh beam has no last_cycle_closed_at, got {data.get('last_cycle_closed_at')!r}"
    )
    assert data["beam_state"] == "ACTIVE", (
        f"a beam under an ACTIVE licence is ACTIVE, got {data['beam_state']}"
    )
    assert data["version"] == 1, f"an unmutated beam is still at version 1, got {data['version']}"


def test_service_cell_listing_paginates_with_total_count_and_has_more(api, agent_headers):
    """Three cells listed two at a time report the pre-window total and the window flag.

    PRD §2.3: "`total_count` is the number of records matching the request's filters before the page window is applied, and `has_more` is true exactly when records remain beyond the current window."
    PRD §2.3: "Unless a specific endpoint says otherwise, collections are ordered by `created_at` ascending."
    PRD §3.2: "All four counters — `committed_terminal_count`, `reserved_slot_count`, `free_slot_count` and `waitlist_depth` — start at 0, and `availability_state` is computed immediately: a cell whose `max_active_terminals` is 0, or whose beam is `SUSPENDED`, or whose beam's `capacity_state` is `SATURATED`, is born `CLOSED`, and any other new cell is born `AVAILABLE`."

    Design: Corner/entities/service_cell_listing_paginates_with_total_count_and_has_more
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_active_license()
    beam = create_beam(license_record["id"], beam_code="BEAM-01", forward_capacity_mbps=100)
    for cell_code in ("CELL-001", "CELL-002", "CELL-003"):
        create_cell(beam["id"], cell_code=cell_code, max_active_terminals=2)

    first_response = api.list_service_cells(
        agent_headers, params={"beam_id": beam["id"], "limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array", (
        "a list endpoint reports response_type 'array'"
    )
    assert first_meta["total_count"] == 3, (
        f"total_count counts all three matching cells before the window, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "has_more must be true while a third cell remains beyond the first window"
    )
    assert len(first_rows) == 2, f"limit=2 returns exactly two rows, got {len(first_rows)}"

    second_response = api.list_service_cells(
        agent_headers, params={"beam_id": beam["id"], "limit": 2, "offset": 2}
    )
    second_rows, second_meta = validate_paginated(second_response)
    assert second_meta["total_count"] == 3, (
        f"total_count ignores the page window, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        "has_more must be false once the window reaches the last record"
    )
    assert len(second_rows) == 1, f"the offset=2 page holds one row, got {len(second_rows)}"

    returned_codes = [row["cell_code"] for row in first_rows + second_rows]
    assert returned_codes == ["CELL-001", "CELL-002", "CELL-003"], (
        f"cells page out in created_at ascending order, got {returned_codes}"
    )
    for row in first_rows + second_rows:
        assert row["availability_state"] == "AVAILABLE", (
            f"cell {row['cell_code']} is born AVAILABLE, got {row['availability_state']}"
        )
        assert row["waitlist_depth"] == 0, (
            f"cell {row['cell_code']} starts with waitlist_depth 0, got {row['waitlist_depth']}"
        )
        assert row["committed_terminal_count"] == 0, (
            f"cell {row['cell_code']} starts with no commitments, "
            f"got {row['committed_terminal_count']}"
        )
        assert row["reserved_slot_count"] == 0, (
            f"cell {row['cell_code']} starts with no holds, got {row['reserved_slot_count']}"
        )


def test_subscription_read_with_unknown_id_returns_subscription_not_found(api, agent_headers):
    """A well-formed but unknown subscription id is a 404, not an empty success body.

    PRD §2.11: "**Path existence** — every id embedded in the URL resolves, validated left to right, so an outer id that does not exist is reported before an inner one is examined."
    PRD §2.11: "HTTP 404, with the identifier naming the missing type: `ERR_SPECTRUM_LICENSE_NOT_FOUND`, `ERR_BEAM_NOT_FOUND`, `ERR_SERVICE_CELL_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_ROAMING_AUTHORIZATION_NOT_FOUND`, `ERR_OUTAGE_EVENT_NOT_FOUND`, `ERR_OUTAGE_CREDIT_NOT_FOUND`."

    Design: Corner/entities/subscription_read_with_unknown_id_returns_subscription_not_found
    """
    set_clock(CLOCK_EPOCH)

    response = api.get_subscription(NON_EXISTENT_UUID, agent_headers)
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND, 404)


# ─────────────────────── required fields and enums ───────────────────────

def test_service_plan_creation_missing_required_field_rejected(api, agent_headers):
    """priority_data_gb carries no default, so omitting it is a malformed request.

    PRD §3.6: "Each plan declares three fair-use parameters alongside its commercial ones: `priority_data_gb`, the whole-gigabyte priority allowance per billing cycle, which must be at least 0; `deprioritized_rate_mbps`, the rate the subscriber falls back to once throttled, which must be strictly greater than zero; and `overage_rate_cents_per_gb`, the cents charged per gigabyte beyond the effective threshold, which must be at least 0 and defaults to 25 when the plan is published without it."
    PRD §2.11: "**Request shape** — required body fields present, enum members valid, numeric ranges honoured."

    Design: Corner/entities/service_plan_creation_missing_required_field_rejected
    """
    set_clock(CLOCK_EPOCH)

    payload = create_service_plan_payload(
        plan_code="PLAN-BROKEN",
        committed_rate_mbps=200,
        priority_tier="PRIORITY_1",
        monthly_fee_cents=9900,
        deprioritized_rate_mbps=20,
        priority_data_gb=None,
        overage_rate_cents_per_gb=None,
        roaming_allowed=None,
        in_motion_allowed=None,
    )
    assert "priority_data_gb" not in payload, "the omission must actually reach the server"

    response = api.create_service_plan(payload, agent_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_spectrum_license_creation_with_invalid_enum_frequency_band_rejected(
    api, compliance_headers
):
    """frequency_band is a closed enum, so an undeclared band is a malformed request.

    PRD §3.1: "Filing supplies the regulator-issued `license_code`, which must be between 1 and 40 characters and unique across all licences; the `jurisdiction_code` the licence authorises service in, between 2 and 8 characters composed of uppercase letters and a single hyphen, such as `US-CA`, `US-NV` or `CA-BC`; the `frequency_band`, which is one of `KA_FORWARD`, `KU_FORWARD` or `KA_RETURN`; the `max_eirp_dbw` ceiling on authorised effective isotropic radiated power, which must be strictly greater than zero; the `expires_at` instant at which the authorisation lapses; and the `consumer_disclosure_version` string, between 1 and 20 characters, naming the disclosure text the jurisdiction mandates."
    PRD §2.11: "**Request shape** — required body fields present, enum members valid, numeric ranges honoured."

    Design: Corner/entities/spectrum_license_creation_with_invalid_enum_frequency_band_rejected
    """
    set_clock(CLOCK_EPOCH)

    payload = create_spectrum_license_payload(
        license_code="LIC-BAD-BAND",
        jurisdiction_code="US-CA",
        frequency_band="S_BAND",
        max_eirp_dbw=62.5,
        expires_at="2027-12-31T00:00:00Z",
        consumer_disclosure_version="CD-2026.1",
        in_motion_permitted=None,
    )

    response = api.create_spectrum_license(payload, compliance_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


# ─────────────────────────── server-side defaults ────────────────────────

def test_beam_creation_applies_default_oversubscription_policy(api, netops_headers):
    """An omitted oversubscription_limit becomes 4.0 and the grace volume starts at 0.

    PRD §3.2: "The beam may also declare its `oversubscription_limit`, the maximum permitted ratio of weighted sold megabits to physical forward capacity; when omitted it defaults to 4.0, and any supplied value must lie between 1.0 and 20.0 inclusive."
    PRD §3.2: "A freshly created beam starts with `weighted_sold_mbps` at 0, `oversubscription_ratio` at 0, `capacity_state` `NORMAL`, `deprioritization_grace_gb` at 0, `billing_cycle_index` at 0 and no `last_cycle_closed_at` recorded."

    Design: Corner/entities/beam_creation_applies_default_oversubscription_policy
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_active_license()

    payload = create_beam_payload(
        spectrum_license_id=license_record["id"],
        beam_code="BEAM-DEF",
        satellite_code="SAT-A",
        forward_capacity_mbps=100,
        oversubscription_limit=None,
    )
    assert "oversubscription_limit" not in payload, "the omission must actually reach the server"

    data = validate_success(api.create_beam(payload, netops_headers), 201)

    assert data["oversubscription_limit"] == pytest.approx(4.0, abs=0.001), (
        f"an omitted oversubscription_limit defaults to 4.0, got {data['oversubscription_limit']}"
    )
    assert data["deprioritization_grace_gb"] == 0, (
        f"a fresh beam's grace volume is 0, got {data['deprioritization_grace_gb']}"
    )
    assert data["capacity_state"] == "NORMAL", (
        f"a fresh beam is NORMAL, got {data['capacity_state']}"
    )


def test_service_plan_creation_applies_boolean_and_overage_defaults(api, agent_headers):
    """A plan published without its optional fields is 25c/GB, fixed-site and non-roaming.

    PRD §3.6: "Each plan declares three fair-use parameters alongside its commercial ones: `priority_data_gb`, the whole-gigabyte priority allowance per billing cycle, which must be at least 0; `deprioritized_rate_mbps`, the rate the subscriber falls back to once throttled, which must be strictly greater than zero; and `overage_rate_cents_per_gb`, the cents charged per gigabyte beyond the effective threshold, which must be at least 0 and defaults to 25 when the plan is published without it."
    PRD §3.7: "The two mobility flags on a plan — `roaming_allowed` and `in_motion_allowed`, both of which default to false when a plan is published without them — gate which modes can even be asked for."
    PRD §2.5: "`updated_at` is refreshed to the logical-clock instant of the most recent mutation of that record, and `version` is an integer that starts at 1 when the record is created and increases by exactly 1 on every mutation, including mutations a record suffers as the downstream hop of somebody else's cascade."

    Design: Corner/entities/service_plan_creation_applies_boolean_and_overage_defaults
    """
    set_clock(CLOCK_EPOCH)

    payload = create_service_plan_payload(
        plan_code="PLAN-BASIC",
        committed_rate_mbps=100,
        priority_tier="BEST_EFFORT",
        monthly_fee_cents=4900,
        priority_data_gb=50,
        deprioritized_rate_mbps=10,
        overage_rate_cents_per_gb=None,
        roaming_allowed=None,
        in_motion_allowed=None,
    )
    for omitted in ("overage_rate_cents_per_gb", "roaming_allowed", "in_motion_allowed"):
        assert omitted not in payload, f"{omitted} must actually be omitted from the request"

    data = validate_success(api.create_service_plan(payload, agent_headers), 201)

    assert data["overage_rate_cents_per_gb"] == 25, (
        "an omitted overage_rate_cents_per_gb defaults to 25 cents per gigabyte, "
        f"got {data['overage_rate_cents_per_gb']}"
    )
    assert data["roaming_allowed"] is False, (
        f"roaming_allowed defaults to false, got {data['roaming_allowed']!r}"
    )
    assert data["in_motion_allowed"] is False, (
        f"in_motion_allowed defaults to false, got {data['in_motion_allowed']!r}"
    )
    assert data["version"] == 1, f"a newly published plan is at version 1, got {data['version']}"


def test_subscriber_creation_ignores_client_supplied_system_fields(api, agent_headers):
    """A client-supplied account_state, ledger balance and version are all ignored.

    PRD §3.3: "The subscriber account it names was opened earlier by an agent supplying an `email` that must contain an at-sign and be unique across accounts, a `full_name`, and the `jurisdiction_code` of the service address on file; a new account is born in `account_state` `PROSPECT` with `credit_balance_cents`, `pending_credit_cents` and `pending_charge_cents` all at 0."
    PRD §2.5: "Every persisted record exposes an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp recording the logical-clock instant of creation."
    PRD §2.5: "`updated_at` is refreshed to the logical-clock instant of the most recent mutation of that record, and `version` is an integer that starts at 1 when the record is created and increases by exactly 1 on every mutation, including mutations a record suffers as the downstream hop of somebody else's cascade."

    Design: Corner/entities/subscriber_creation_with_extra_field_account_state_ignored_input
    """
    set_clock(CLOCK_EPOCH)

    payload = create_subscriber_payload(
        email="sub1@example.com",
        full_name="Sub One",
        jurisdiction_code="US-CA",
        account_state="ACTIVE",
        credit_balance_cents=5000,
        version=9,
    )
    data = validate_success(api.create_subscriber(payload, agent_headers), 201)

    assert data["account_state"] == "PROSPECT", (
        f"a new account is born PROSPECT whatever the client sent, got {data['account_state']}"
    )
    assert data["credit_balance_cents"] == 0, (
        f"credit_balance_cents starts at 0 whatever the client sent, "
        f"got {data['credit_balance_cents']}"
    )
    assert data["pending_credit_cents"] == 0, (
        f"pending_credit_cents starts at 0, got {data['pending_credit_cents']}"
    )
    assert data["pending_charge_cents"] == 0, (
        f"pending_charge_cents starts at 0, got {data['pending_charge_cents']}"
    )
    assert data["version"] == 1, (
        f"version starts at 1 whatever the client sent, got {data['version']}"
    )
    assert is_valid_uuid(data["id"]), (
        f"id must be a server-minted UUID with no type prefix, got {data['id']!r}"
    )
    assert data["created_at"] == EPOCH_EMITTED, (
        f"created_at must be the logical-clock instant {EPOCH_EMITTED}, got {data['created_at']!r}"
    )
    assert data["updated_at"] == EPOCH_EMITTED, (
        f"updated_at must be the logical-clock instant {EPOCH_EMITTED}, got {data['updated_at']!r}"
    )


# ────────────────────── computed fields and immutability ─────────────────

def test_obstruction_scan_computed_pct_and_verdict_at_the_marginal_boundary(
    api, logistics_headers
):
    """16 obstructed of 200 samples is exactly 8.00 pct, the closed top of MARGINAL.

    PRD §3.4: "The survey computes `obstruction_pct` as one hundred times the obstructed count divided by the total count, rounded half up to 2 decimal places, and derives a `scan_verdict` from three bands: `PASS` when `obstruction_pct` is at most 2.00, `MARGINAL` when it is strictly greater than 2.00 and at most 8.00, and `FAIL` when it is strictly greater than 8.00."
    PRD §3.4: "The survey's `scanned_at` is the logical clock's current instant."
    PRD §3.4: "Recording a survey immediately refreshes the terminal's `last_scan_verdict` to the newly computed verdict, since a survey taken now is by construction newer than both the terminal's `created_at` and any `ownership_changed_at`."

    Design: Corner/entities/obstruction_scan_computed_pct_and_verdict_at_the_marginal_boundary
    """
    set_clock(CLOCK_EPOCH)
    subscriber = create_subscriber(index=1)
    terminal = ship_terminal(subscriber["id"], index=1)
    deliver_terminal(terminal["id"])

    data = validate_success(
        api.create_obstruction_scan(
            terminal["id"],
            obstruction_scan_payload(obstructed_sample_count=16, total_sample_count=200),
            make_subscriber_headers(subscriber["id"]),
        ),
        201,
    )

    assert data["terminal_id"] == terminal["id"], "the survey names the surveyed terminal"
    assert data["obstructed_sample_count"] == 16, "obstructed_sample_count must echo the filing"
    assert data["total_sample_count"] == 200, "total_sample_count must echo the filing"
    assert data["obstruction_pct"] == pytest.approx(8.00, abs=0.001), (
        f"16 of 200 samples is 8.00 percent, got {data['obstruction_pct']}"
    )
    assert data["scan_verdict"] == "MARGINAL", (
        f"8.00 percent sits at the closed top of the MARGINAL band, got {data['scan_verdict']}"
    )
    assert data["scanned_at"] == EPOCH_EMITTED, (
        f"scanned_at is the logical clock's instant {EPOCH_EMITTED}, got {data['scanned_at']!r}"
    )

    terminal_after = validate_success(api.get_terminal(terminal["id"], logistics_headers), 200)
    assert terminal_after["last_scan_verdict"] == "MARGINAL", (
        "recording the survey refreshes last_scan_verdict to the new verdict, "
        f"got {terminal_after['last_scan_verdict']}"
    )


def test_obstruction_scan_is_immutable_with_no_version_field(api, logistics_headers):
    """A second survey appends a row; the first keeps its computed values untouched.

    PRD §2.5: "An obstruction scan and a metered usage record expose only `id` and `created_at`; they have no `updated_at` and no `version`, and nothing in the system ever mutates them after creation."
    PRD §2.3: "The obstruction-scan collection for a terminal is returned newest first, ordered by `scanned_at` descending and then by `created_at` descending."
    PRD §3.4: "The survey computes `obstruction_pct` as one hundred times the obstructed count divided by the total count, rounded half up to 2 decimal places, and derives a `scan_verdict` from three bands: `PASS` when `obstruction_pct` is at most 2.00, `MARGINAL` when it is strictly greater than 2.00 and at most 8.00, and `FAIL` when it is strictly greater than 8.00."
    PRD §3.4: "It is the verdict of the newest survey whose `scanned_at` is at or after the later of the terminal's `created_at` and its `ownership_changed_at`, and it is empty when no survey satisfies that test."

    Design: Corner/entities/obstruction_scan_is_immutable_with_no_version_field
    """
    set_clock(CLOCK_EPOCH)
    subscriber = create_subscriber(index=1)
    subscriber_headers_owned = make_subscriber_headers(subscriber["id"])
    terminal = ship_terminal(subscriber["id"], index=1)
    deliver_terminal(terminal["id"])

    first_scan = validate_success(
        api.create_obstruction_scan(
            terminal["id"],
            obstruction_scan_payload(obstructed_sample_count=16, total_sample_count=200),
            subscriber_headers_owned,
        ),
        201,
    )
    set_clock("2026-08-02T00:00:00Z")

    second_scan = validate_success(
        api.create_obstruction_scan(
            terminal["id"],
            obstruction_scan_payload(obstructed_sample_count=1, total_sample_count=200),
            subscriber_headers_owned,
        ),
        201,
    )
    assert_append_only_fields(second_scan)
    assert second_scan["obstruction_pct"] == pytest.approx(0.50, abs=0.001), (
        f"1 of 200 samples is 0.50 percent, got {second_scan['obstruction_pct']}"
    )
    assert second_scan["scan_verdict"] == "PASS", (
        f"0.50 percent is inside the PASS band, got {second_scan['scan_verdict']}"
    )
    assert second_scan["id"] != first_scan["id"], (
        "a second survey appends a new row rather than mutating the first"
    )

    rows, meta = validate_paginated(
        api.list_obstruction_scans(terminal["id"], logistics_headers, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2, (
        f"both surveys are persisted, got total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == second_scan["id"], (
        "the survey collection is returned newest first by scanned_at descending"
    )

    stored_first = next(row for row in rows if row["id"] == first_scan["id"])
    assert_append_only_fields(stored_first)
    assert stored_first["obstruction_pct"] == pytest.approx(8.00, abs=0.001), (
        f"the first survey's percentage is unchanged, got {stored_first['obstruction_pct']}"
    )
    assert stored_first["scan_verdict"] == "MARGINAL", (
        f"the first survey's verdict is unchanged, got {stored_first['scan_verdict']}"
    )
    assert stored_first["scanned_at"] == EPOCH_EMITTED, (
        f"the first survey keeps its original scanned_at, got {stored_first['scanned_at']!r}"
    )

    terminal_after = validate_success(api.get_terminal(terminal["id"], logistics_headers), 200)
    assert terminal_after["last_scan_verdict"] == "PASS", (
        "the newest qualifying survey supplies last_scan_verdict, "
        f"got {terminal_after['last_scan_verdict']}"
    )


# ─────────────────────── body reference resolution ───────────────────────

def test_service_cell_creation_with_unknown_beam_returns_beam_not_found(api, netops_headers):
    """An unknown beam_id in the body is a 404 and leaves no dangling cell behind.

    PRD §2.11: "**Body reference existence** — every foreign key in the body resolves: `spectrum_license_id`, `beam_id`, `subscriber_id`, `service_cell_id`, `requested_plan_id`, `service_order_id`, `terminal_id`, `subscription_id`, `new_service_plan_id`, `new_subscriber_id` and `target_service_cell_id`."
    PRD §2.11: "HTTP 404, using `ERR_SPECTRUM_LICENSE_NOT_FOUND`, `ERR_BEAM_NOT_FOUND`, `ERR_SERVICE_CELL_NOT_FOUND`, `ERR_SERVICE_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND` or `ERR_SUBSCRIPTION_NOT_FOUND` as appropriate."
    PRD §3.2: "Creating one supplies its `cell_code`, between 1 and 40 characters and unique across cells, which doubles as the deterministic sweep-order key when an ops run walks a beam's cells; the `beam_id` of the beam that serves it; the `jurisdiction_code` of the footprint it covers, between 2 and 8 characters; and `max_active_terminals`, the hard slot ceiling, which must be at least 0."

    Design: Corner/entities/service_cell_creation_with_unknown_beam_returns_beam_not_found
    """
    set_clock(CLOCK_EPOCH)

    payload = create_service_cell_payload(
        beam_id=NON_EXISTENT_UUID,
        cell_code="CELL-ORPHAN",
        jurisdiction_code="US-CA",
        max_active_terminals=2,
    )
    response = api.create_service_cell(payload, netops_headers)
    validate_error(response, ApiErrorId.ERR_BEAM_NOT_FOUND, 404)

    _rows, meta = validate_paginated(api.list_service_cells(netops_headers))
    assert meta["total_count"] == 0, (
        f"the rejected filing must not have created a cell, got total_count {meta['total_count']}"
    )


def test_service_order_with_unknown_plan_returns_service_plan_not_found(
    api, agent_headers, netops_headers
):
    """A valid subscriber and cell do not rescue an unknown requested_plan_id.

    PRD §2.11: "**Body reference existence** — every foreign key in the body resolves: `spectrum_license_id`, `beam_id`, `subscriber_id`, `service_cell_id`, `requested_plan_id`, `service_order_id`, `terminal_id`, `subscription_id`, `new_service_plan_id`, `new_subscriber_id` and `target_service_cell_id`."
    PRD §2.11: "HTTP 404, using `ERR_SPECTRUM_LICENSE_NOT_FOUND`, `ERR_BEAM_NOT_FOUND`, `ERR_SERVICE_CELL_NOT_FOUND`, `ERR_SERVICE_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND` or `ERR_SUBSCRIPTION_NOT_FOUND` as appropriate."
    PRD §3.3: "The cell's `reserved_slot_count` increases by 1, its `free_slot_count` and `availability_state` are recomputed, and the cell's `version` increases by 1."
    PRD §3.3: "The subscriber account it names was opened earlier by an agent supplying an `email` that must contain an at-sign and be unique across accounts, a `full_name`, and the `jurisdiction_code` of the service address on file; a new account is born in `account_state` `PROSPECT` with `credit_balance_cents`, `pending_credit_cents` and `pending_charge_cents` all at 0."

    Design: Corner/entities/service_order_with_unknown_plan_returns_service_plan_not_found
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_active_license()
    beam = create_beam(license_record["id"], beam_code="BEAM-01", forward_capacity_mbps=100)
    cell = create_cell(beam["id"], cell_code="CELL-001", max_active_terminals=2)
    subscriber = create_subscriber(index=1)

    response = api.create_service_order(
        create_service_order_payload(
            subscriber_id=subscriber["id"],
            service_cell_id=cell["id"],
            requested_plan_id=NON_EXISTENT_UUID,
        ),
        agent_headers,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_PLAN_NOT_FOUND, 404)

    cell_after = validate_success(api.get_service_cell(cell["id"], netops_headers), 200)
    assert cell_after["reserved_slot_count"] == 0, (
        f"the rejected filing must consume no slot, got {cell_after['reserved_slot_count']}"
    )
    assert cell_after["version"] == cell["version"], (
        f"an untouched cell keeps version {cell['version']}, got {cell_after['version']}"
    )

    subscriber_after = validate_success(api.get_subscriber(subscriber["id"], agent_headers), 200)
    assert subscriber_after["account_state"] == "PROSPECT", (
        f"the account stays PROSPECT, got {subscriber_after['account_state']}"
    )
