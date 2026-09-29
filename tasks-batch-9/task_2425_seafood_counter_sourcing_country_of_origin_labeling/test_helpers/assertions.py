"""Entity assertions and domain invariant checkers for the Seafood Counter Cool Ops API."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

WEIGHT_TOLERANCE = 0.0005
TEMPERATURE_TOLERANCE = 0.005
INDEX_TOLERANCE = 0.005


# --------------------------------------------------------------------------
# Generic field-shape helpers
# --------------------------------------------------------------------------
def assert_identity_fields(data: dict) -> None:
    """Server-minted `id` as a bare UUID plus an ISO 8601 `created_at` (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def assert_versioned_fields(data: dict) -> None:
    """Records other than a Species or an IceBedReading also carry updated_at + version."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_no_version_fields(data: dict) -> None:
    """A Species and an IceBedReading carry neither updated_at nor version (PRD §2.4)."""
    assert "updated_at" not in data, "updated_at must not appear on this record"
    assert "version" not in data, "version must not appear on this record"


def _parse_instant(value: str):
    assert isinstance(value, str), f"expected an ISO 8601 timestamp string, got {value!r}"
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def assert_instant(actual, expected) -> None:
    """Compare two ISO 8601 UTC timestamps as instants.

    PRD §2.4 fixes the rendering of `created_at` as "an ISO 8601 UTC instant with three
    fractional digits" but does not pin a fractional-digit count per field for every other
    timestamp (the logical-clock-stamped fields, or the client-supplied instants a record
    copies), so the assertion is on the instant the PRD names rather than on its spelling.
    """
    assert is_iso8601_timestamp(actual), f"expected an ISO 8601 UTC timestamp, got {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_weight(actual, expected) -> None:
    """Weights are decimals carried to exactly 3 decimal places (PRD §2.7)."""
    assert abs(float(actual) - float(expected)) < WEIGHT_TOLERANCE, (
        f"Expected weight {expected}, got {actual}"
    )


def assert_temperature(actual, expected) -> None:
    """Probe temperatures are decimals carried to exactly 1 decimal place (PRD §2.7)."""
    assert abs(float(actual) - float(expected)) < TEMPERATURE_TOLERANCE, (
        f"Expected temperature {expected}, got {actual}"
    )


def assert_risk_index(actual, expected) -> None:
    """Substitution risk indices are decimals carried to 2 decimal places (PRD §2.7)."""
    assert abs(float(actual) - float(expected)) < INDEX_TOLERANCE, (
        f"Expected risk index {expected}, got {actual}"
    )


def assert_cents(actual, expected) -> None:
    """Money is always an integer count of cents (PRD §2.7)."""
    assert isinstance(actual, int), f"Monetary field must be an integer, got {actual!r}"
    assert actual == expected, f"Expected {expected} cents, got {actual}"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_counter(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["posture"] in ("OPEN", "RESTRICTED", "SUSPENDED")
    assert isinstance(data["store_number"], str) and len(data["store_number"]) == 4
    assert isinstance(data["case_slot_count"], int)
    for field in (
        "verification_cycle_index",
        "open_excursion_count",
        "violation_points",
        "last_cycle_required_samples",
        "shrink_gross_cents",
        "shrink_net_cents",
        "recovered_conversion_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_supplier(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("GOOD_STANDING", "PROBATION", "SUSPENDED")
    for field in (
        "lifetime_sample_count",
        "lifetime_mismatch_count",
        "chargeback_assessed_total_cents",
        "chargeback_outstanding_cents",
        "chargeback_settled_cents",
        "chargeback_reversed_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_species(data: dict) -> None:
    assert_identity_fields(data)
    assert_no_version_fields(data)
    assert isinstance(data["acceptable_market_names"], list)
    for flag in ("simp_covered", "high_risk_substitution", "sustainability_program_eligible"):
        assert isinstance(data[flag], bool), f"{flag} must be a boolean"


def assert_supplier_lot(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["intake_status"] in ("RECEIVED", "CASED", "HELD", "DEPLETED", "DISPOSED")
    assert data["label_status"] in ("UNVERIFIED", "SAMPLED", "VERIFIED", "MISMATCHED", "RELABELED")
    assert data["chargeback_status"] in ("NONE", "ASSESSED", "SETTLED", "REVERSED")
    assert data["harvest_method"] in (
        "WILD_NET", "WILD_LONGLINE", "WILD_TRAP", "AQUACULTURE_POND", "AQUACULTURE_PEN",
    )
    assert data["production_method"] in ("WILD", "FARMED")
    assert len(data["origin_country_code"]) == 2
    assert isinstance(data["chargeback_assessed_cents"], int)


def assert_case_label(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("PUBLISHED", "WITHDRAWN")
    assert data["production_method_statement"] in ("WILD CAUGHT", "FARM RAISED")
    assert data["frozen_disclosure_statement"] in (
        "PREVIOUSLY FROZEN", "FRESH - NEVER FROZEN", "FRESH",
    )


def assert_advertised_item(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("DRAFT", "APPROVED", "PUBLISHED", "CLOSED", "RETRACTED", "REJECTED")
    assert data["cool_review_status"] in ("COOL_PENDING", "COOL_CLEARED", "COOL_REJECTED")
    assert data["claim_review_status"] in ("CLAIM_PENDING", "CLAIM_CLEARED", "CLAIM_REJECTED")


def assert_ice_bed_reading(data: dict) -> None:
    assert_identity_fields(data)
    assert_no_version_fields(data)
    assert isinstance(data["breach"], bool), "breach must be a boolean"
    assert isinstance(data["case_slot"], int)


def assert_cold_chain_excursion(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("OPEN", "RESOLVED_RELEASED", "RESOLVED_DISPOSED")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["exposure_minutes"], int), "exposure_minutes must be whole minutes"


def assert_verification_sample(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("DRAFT", "IN_LAB", "MATCH", "MISMATCH", "DISPUTED", "VOIDED")
    assert isinstance(data["retest_count"], int)
    assert isinstance(data["cycle_index"], int)


def assert_simp_document(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "DEFICIENT")
    assert isinstance(data["amendment_count"], int)


def assert_certification(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("PENDING_REVIEW", "ACTIVE", "REVOKED", "EXPIRED")


def assert_shrink_event(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("VALUED", "CONVERSION_APPROVED", "CONVERTED", "POSTED", "REVERSED")
    assert data["reason"] in ("UNSOLD_FRESH", "MISLABEL_DESTRUCTION", "COLD_CHAIN_DISPOSAL")
    for field in ("provisional_value_cents", "final_value_cents", "recovery_credit_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"


def assert_compliance_violation(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("OPEN", "CURED", "EXPUNGED")
    assert data["category"] in (
        "SPECIES_SUBSTITUTION", "COOL_MISSING", "FROZEN_DISCLOSURE",
        "SIMP_DEFICIENT", "COLD_CHAIN", "UNSUBSTANTIATED_CLAIM",
    )
    assert isinstance(data["points"], int)


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_counter_shrink_ledger_identity(counter: dict) -> None:
    """PRD §2.11: gross equals net plus recovered at all times."""
    assert counter["shrink_gross_cents"] == (
        counter["shrink_net_cents"] + counter["recovered_conversion_cents"]
    ), (
        "shrink_gross_cents must equal shrink_net_cents + recovered_conversion_cents, got "
        f"{counter['shrink_gross_cents']} vs {counter['shrink_net_cents']} + "
        f"{counter['recovered_conversion_cents']}"
    )


def assert_supplier_chargeback_identity(supplier: dict) -> None:
    """PRD §2.11: assessed total equals outstanding plus settled plus reversed."""
    assert supplier["chargeback_assessed_total_cents"] == (
        supplier["chargeback_outstanding_cents"]
        + supplier["chargeback_settled_cents"]
        + supplier["chargeback_reversed_cents"]
    ), (
        "chargeback_assessed_total_cents must equal outstanding + settled + reversed, got "
        f"{supplier['chargeback_assessed_total_cents']} vs "
        f"{supplier['chargeback_outstanding_cents']} + "
        f"{supplier['chargeback_settled_cents']} + {supplier['chargeback_reversed_cents']}"
    )


def assert_shrink_value_identity(event: dict) -> None:
    """PRD §3.9: provisional_value_cents always equals final plus recovery credit."""
    assert event["provisional_value_cents"] == (
        event["final_value_cents"] + event["recovery_credit_cents"]
    ), (
        "provisional_value_cents must equal final_value_cents + recovery_credit_cents, got "
        f"{event['provisional_value_cents']} vs {event['final_value_cents']} + "
        f"{event['recovery_credit_cents']}"
    )


def assert_error_envelope_shape(body: dict) -> None:
    """PRD §2.2: an error envelope's meta carries only the two request fields and data
    carries only error_id and message."""
    assert body["response_type"] == "error", f"response_type must be 'error', got {body!r}"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must contain only the two request fields, got {sorted(meta.keys())}"
    )
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error data must contain only error_id and message, got {sorted(body['data'].keys())}"
    )
