"""Domain assertions shared across the suite.

These wrap the recurring structural contracts — envelope shape, the five derived
plan-account figures, the payee-account totals recomputed from the `ISSUED` set,
the append-only resource shape, the sweep report and the settlement breakdown —
so individual tests read as domain statements rather than dictionary poking.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .constants import (
    API_REQUEST_ID_PREFIX,
    ENVELOPE_META_KEYS,
    PAGINATION_META_KEYS,
)
from .types import (
    APPEND_ONLY_RESOURCE_TYPES,
    DISTRIBUTION_ISSUED,
    HOLD_HELD,
)


# ─── Envelope ─────────────────────────────────────────────────────────────


def assert_envelope_meta(body):
    """Every response carries a `req_`-prefixed id and an ISO 8601 timestamp."""
    assert "meta" in body, f"response body has no meta: {body}"
    meta = body["meta"]
    api_request_id = meta.get("api_request_id")
    assert isinstance(api_request_id, str), f"api_request_id missing: {meta}"
    assert api_request_id.startswith(
        API_REQUEST_ID_PREFIX
    ), f"api_request_id must start with 'req_': {api_request_id}"
    timestamp = meta.get("api_request_timestamp")
    assert is_iso8601_timestamp(
        timestamp
    ), f"api_request_timestamp not ISO 8601: {timestamp}"
    return meta


def assert_single_resource(response, expected_status=200):
    """A single-resource success: object envelope with no pagination fields."""
    data = validate_success(response, expected_status)
    body = response.json()
    meta = assert_envelope_meta(body)
    assert (
        body.get("response_type") == "object"
    ), f"expected response_type 'object', got {body.get('response_type')}"
    for key in PAGINATION_META_KEYS:
        assert key not in meta, f"single-resource meta must omit '{key}': {meta}"
    return data


def assert_list_response(response):
    """A list success: array envelope carrying all four pagination fields."""
    rows, meta = validate_paginated(response)
    body = response.json()
    assert_envelope_meta(body)
    assert (
        body.get("response_type") == "array"
    ), f"expected response_type 'array', got {body.get('response_type')}"
    return rows, meta


def assert_error_envelope(response, error_id, expected_status=None):
    """An error body: `response_type` 'error' and meta limited to two keys."""
    data = validate_error(response, error_id, expected_status)
    body = response.json()
    meta = assert_envelope_meta(body)
    assert (
        body.get("response_type") == "error"
    ), f"expected response_type 'error', got {body.get('response_type')}"
    assert set(meta.keys()) == set(
        ENVELOPE_META_KEYS
    ), f"error meta must contain only the two envelope keys: {meta}"
    assert isinstance(data.get("message"), str) and data["message"], (
        f"error data must carry a human-readable message: {data}"
    )
    return data


# ─── Resource shape ───────────────────────────────────────────────────────


def assert_identity_fields(resource):
    """A UUID `id` with no type prefix plus an ISO 8601 `created_at`."""
    assert is_valid_uuid(resource.get("id")), f"id is not a UUID: {resource.get('id')}"
    assert is_iso8601_timestamp(
        resource.get("created_at")
    ), f"created_at not ISO 8601: {resource.get('created_at')}"


def assert_versioned_resource(resource, expected_version=None):
    """A mutable resource carries `updated_at` and an integer `version`."""
    assert_identity_fields(resource)
    assert is_iso8601_timestamp(
        resource.get("updated_at")
    ), f"updated_at not ISO 8601: {resource.get('updated_at')}"
    version = resource.get("version")
    assert isinstance(version, int), f"version must be an integer: {version!r}"
    if expected_version is not None:
        assert version == expected_version, (
            f"expected version {expected_version}, got {version}"
        )


def assert_append_only_resource(resource, resource_type=None):
    """An append-only record exposes neither `updated_at` nor `version`."""
    if resource_type is not None:
        assert resource_type in APPEND_ONLY_RESOURCE_TYPES, (
            f"{resource_type} is not one of the append-only resource types"
        )
    assert_identity_fields(resource)
    assert "updated_at" not in resource, (
        f"append-only resource must not expose updated_at: {resource}"
    )
    assert "version" not in resource, (
        f"append-only resource must not expose version: {resource}"
    )


def assert_fields_absent(resource, field_names):
    for name in field_names:
        assert name not in resource, f"field '{name}' must be absent: {resource}"


def assert_fields_equal(resource, expected):
    """Assert an exact value for each named field, reporting the whole row."""
    for name, value in expected.items():
        assert name in resource, f"field '{name}' missing from {resource}"
        assert resource[name] == value, (
            f"field '{name}': expected {value!r}, got {resource[name]!r}"
        )


# ─── Derived balances ─────────────────────────────────────────────────────


def assert_plan_account_figures(
    account,
    vested_balance_cents=None,
    assignable_base_cents=None,
    after_tax_basis_cents=None,
    held_amount_cents=None,
    available_balance_cents=None,
):
    """Check the named derived figures and the available-balance identity."""
    expected = {
        "vested_balance_cents": vested_balance_cents,
        "assignable_base_cents": assignable_base_cents,
        "after_tax_basis_cents": after_tax_basis_cents,
        "held_amount_cents": held_amount_cents,
        "available_balance_cents": available_balance_cents,
    }
    for name, value in expected.items():
        if value is not None:
            assert account.get(name) == value, (
                f"{name}: expected {value}, got {account.get(name)}"
            )
    assert (
        account["available_balance_cents"]
        == account["vested_balance_cents"] - account["held_amount_cents"]
    ), f"available balance is not vested minus held: {account}"


def assert_derived_from_money_sources(account, money_sources, holds=()):
    """Recompute all five derived figures from the account's own children."""
    vested = sum(source["balance_cents"] for source in money_sources)
    assignable = sum(
        source["balance_cents"] for source in money_sources if source["is_assignable"]
    )
    basis = sum(
        source["basis_cents"] for source in money_sources if source["is_assignable"]
    )
    held = sum(
        hold["hold_amount_cents"] for hold in holds if hold["status"] == HOLD_HELD
    )
    assert_plan_account_figures(
        account,
        vested_balance_cents=vested,
        assignable_base_cents=assignable,
        after_tax_basis_cents=basis,
        held_amount_cents=held,
        available_balance_cents=vested - held,
    )


def assert_ap_account_totals(account, distributions, established_balance_cents=None,
                             established_basis_cents=None):
    """Payee totals are recomputed from the `ISSUED` set, never adjusted."""
    issued = [row for row in distributions if row["status"] == DISTRIBUTION_ISSUED]
    gross = sum(row["gross_amount_cents"] for row in issued)
    assert account["total_distributed_gross_cents"] == gross, (
        f"total_distributed_gross_cents: expected {gross}, "
        f"got {account['total_distributed_gross_cents']}"
    )
    if established_balance_cents is not None:
        assert account["balance_cents"] == established_balance_cents - gross, (
            f"balance_cents: expected {established_balance_cents - gross}, "
            f"got {account['balance_cents']}"
        )
    if established_basis_cents is not None:
        recovered = sum(row["basis_recovery_cents"] for row in issued)
        assert account["after_tax_basis_cents"] == established_basis_cents - recovered, (
            f"after_tax_basis_cents: expected "
            f"{established_basis_cents - recovered}, "
            f"got {account['after_tax_basis_cents']}"
        )


# ─── Money conservation ───────────────────────────────────────────────────


def assert_conserved(total_before, parts, label="custody"):
    """The parts of a split must sum back to the whole they came from."""
    total_after = sum(parts)
    assert total_after == total_before, (
        f"{label} not conserved: {total_before} != sum{tuple(parts)} = {total_after}"
    )


def assert_signed_ledger_nets_to(rows, field, expected=0):
    """An append-only ledger nets to a stated figure across all its lines."""
    total = sum(row[field] for row in rows)
    assert total == expected, (
        f"ledger field '{field}' nets to {total}, expected {expected}"
    )


# ─── Correspondence ───────────────────────────────────────────────────────


def communication_tuple(row):
    """Reduce a correspondence row to the four fields the cascades pin."""
    return (
        row["recipient_type"],
        row["template_code"],
        row["disclosure_level"],
        row["origin"],
    )


def assert_communication_sequence(rows, expected_tuples):
    """Correspondence appended by a cascade must appear in the pinned order."""
    actual = [communication_tuple(row) for row in rows]
    assert len(actual) == len(expected_tuples), (
        f"expected exactly {len(expected_tuples)} communications, got "
        f"{len(actual)}: {actual}"
    )
    assert actual == list(expected_tuples), (
        f"correspondence order mismatch:\n expected {list(expected_tuples)}\n"
        f" actual   {actual}"
    )


def assert_sent_at_all(rows, expected_sent_at):
    for row in rows:
        assert row["sent_at"] == expected_sent_at, (
            f"expected sent_at {expected_sent_at}, got {row['sent_at']}"
        )


def assert_attorney_email_absent(rows):
    """System correspondence to the two principals carries no counsel address."""
    for row in rows:
        assert row.get("attorney_email") is None, (
            f"attorney_email should be null on this entry: {row}"
        )


# ─── Ordering ─────────────────────────────────────────────────────────────


def assert_ascending(rows, *keys):
    """Rows are ordered ascending on the given key tuple."""
    extracted = [tuple(row[key] for key in keys) for row in rows]
    assert extracted == sorted(extracted), (
        f"rows are not ascending on {keys}: {extracted}"
    )


def assert_ids_in_order(rows, expected_ids):
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"expected ids {list(expected_ids)}, got {actual}"
    )


def assert_statuses_in_order(rows, expected_statuses, field="status"):
    actual = [row[field] for row in rows]
    assert actual == list(expected_statuses), (
        f"expected {field} sequence {list(expected_statuses)}, got {actual}"
    )


# ─── Sweep report ─────────────────────────────────────────────────────────


def assert_sweep_report(
    data,
    expired_hold_ids=None,
    lapsed_case_ids=None,
    denied_draft_order_ids=None,
    expired_notice_ids=None,
    closed_ap_account_ids=None,
):
    """Check the sweep's five identifier lists; unspecified lists are ignored."""
    expected = {
        "expired_hold_ids": expired_hold_ids,
        "lapsed_case_ids": lapsed_case_ids,
        "denied_draft_order_ids": denied_draft_order_ids,
        "expired_notice_ids": expired_notice_ids,
        "closed_ap_account_ids": closed_ap_account_ids,
    }
    for name, value in expected.items():
        assert name in data, f"sweep report missing '{name}': {data}"
        if value is not None:
            assert data[name] == list(value), (
                f"sweep report '{name}': expected {list(value)}, got {data[name]}"
            )


def assert_sweep_found_nothing(data):
    """A sweep with nothing left to do reports five empty identifier lists."""
    assert_sweep_report(
        data,
        expired_hold_ids=[],
        lapsed_case_ids=[],
        denied_draft_order_ids=[],
        expired_notice_ids=[],
        closed_ap_account_ids=[],
    )


# ─── Settlement and reporting ─────────────────────────────────────────────


def assert_settlement(
    distribution,
    gross_amount_cents=None,
    basis_recovery_cents=None,
    taxable_amount_cents=None,
    federal_withheld_cents=None,
    net_before_fee_cents=None,
    admin_fee_cents=None,
    net_amount_cents=None,
    distribution_code=None,
    tax_year=None,
):
    """Assert the seven-step settlement breakdown plus its two identities."""
    expected = {
        "gross_amount_cents": gross_amount_cents,
        "basis_recovery_cents": basis_recovery_cents,
        "taxable_amount_cents": taxable_amount_cents,
        "federal_withheld_cents": federal_withheld_cents,
        "net_before_fee_cents": net_before_fee_cents,
        "admin_fee_cents": admin_fee_cents,
        "net_amount_cents": net_amount_cents,
        "distribution_code": distribution_code,
        "tax_year": tax_year,
    }
    for name, value in expected.items():
        if value is not None:
            assert distribution.get(name) == value, (
                f"{name}: expected {value}, got {distribution.get(name)}"
            )
    assert (
        distribution["taxable_amount_cents"]
        == distribution["gross_amount_cents"] - distribution["basis_recovery_cents"]
    ), f"taxable is not gross minus basis recovery: {distribution}"
    assert (
        distribution["net_amount_cents"]
        == distribution["net_before_fee_cents"] - distribution["admin_fee_cents"]
    ), f"net is not net-before-fee minus the fee: {distribution}"


def assert_tax_line(
    row,
    reportable_gross_cents=None,
    reportable_taxable_cents=None,
    federal_withheld_cents=None,
    distribution_code=None,
    tax_year=None,
    correction_of_tax_report_id=...,
):
    """Assert one reporting line, including whether it is a correction."""
    expected = {
        "reportable_gross_cents": reportable_gross_cents,
        "reportable_taxable_cents": reportable_taxable_cents,
        "federal_withheld_cents": federal_withheld_cents,
        "distribution_code": distribution_code,
        "tax_year": tax_year,
    }
    for name, value in expected.items():
        if value is not None:
            assert row.get(name) == value, (
                f"{name}: expected {value}, got {row.get(name)}"
            )
    if correction_of_tax_report_id is not ...:
        assert row.get("correction_of_tax_report_id") == correction_of_tax_report_id, (
            f"correction_of_tax_report_id: expected "
            f"{correction_of_tax_report_id}, got "
            f"{row.get('correction_of_tax_report_id')}"
        )


def assert_tax_ledger_nets_to_zero(rows):
    """A void leaves the year's three reported figures at zero across the rows."""
    for field in (
        "reportable_gross_cents",
        "reportable_taxable_cents",
        "federal_withheld_cents",
    ):
        assert_signed_ledger_nets_to(rows, field, 0)


def assert_tax_ledger_totals(rows, gross, taxable, withheld):
    assert_signed_ledger_nets_to(rows, "reportable_gross_cents", gross)
    assert_signed_ledger_nets_to(rows, "reportable_taxable_cents", taxable)
    assert_signed_ledger_nets_to(rows, "federal_withheld_cents", withheld)


# ─── Holds and cases ──────────────────────────────────────────────────────


def assert_hold(
    hold,
    status=None,
    hold_amount_cents=None,
    placed_at=None,
    expires_at=None,
    segregation_date=...,
    earnings_growth_bps=None,
    earnings_adjustment_cents=None,
):
    expected = {
        "status": status,
        "hold_amount_cents": hold_amount_cents,
        "placed_at": placed_at,
        "expires_at": expires_at,
        "earnings_growth_bps": earnings_growth_bps,
        "earnings_adjustment_cents": earnings_adjustment_cents,
    }
    for name, value in expected.items():
        if value is not None:
            assert hold.get(name) == value, (
                f"hold {name}: expected {value}, got {hold.get(name)}"
            )
    if segregation_date is not ...:
        assert hold.get("segregation_date") == segregation_date, (
            f"hold segregation_date: expected {segregation_date}, "
            f"got {hold.get('segregation_date')}"
        )


def assert_case_dimensions(case, review_status=None, segregation_status=None,
                           version=None):
    """The case's two independent dimensions, read from the same row."""
    if review_status is not None:
        assert case["review_status"] == review_status, (
            f"review_status: expected {review_status}, got {case['review_status']}"
        )
    if segregation_status is not None:
        assert case["segregation_status"] == segregation_status, (
            f"segregation_status: expected {segregation_status}, "
            f"got {case['segregation_status']}"
        )
    if version is not None:
        assert case["version"] == version, (
            f"case version: expected {version}, got {case['version']}"
        )
