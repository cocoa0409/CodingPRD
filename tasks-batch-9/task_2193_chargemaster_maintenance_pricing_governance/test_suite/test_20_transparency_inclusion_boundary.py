"""The empty-collection edge of a transparency build: zero rows versus exactly one."""
import hashlib

from test_helpers import (
    setup_transparency_empty_chargemaster_scenario,
    build_transparency_file, file_lifecycle, read_file,
    create_active_item, read_facility, read_item,
)


def _content_hash(*rows: str) -> str:
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def test_a_build_over_an_empty_chargemaster_counts_zero_rows_and_fails_validation():
    """PRD §3.10: "From that ordered set, `included_item_count` is the row count and
    `total_gross_charge_cents` is the sum of `gross_charge_cents` over the rows."
    PRD §3.10: "`content_hash` is a SHA-256 digest over the ordered rows, each serialized as
    its `cdm_number`, its revenue code, its `code_value` (or an empty string when null) and
    its `gross_charge_cents` joined by vertical bars, with rows joined by newlines —
    deterministic for a given inclusion set and ordering, and recomputed on every build."
    PRD §3.10: "It gains the string `'NO_PUBLISHABLE_ITEMS'` when `included_item_count` is 0,
    the string `'NO_ACTIVE_PAYER_COLUMNS'` when `payer_column_count` is 0, and the string
    `'STALE_PRICED_ITEMS'` when any charge item of the facility whose `lifecycle_status` is
    `ACTIVE` has `price_status` of `PRICE_STALE`."
    PRD §3.10: "The `VALIDATE` action routes `BUILDING → VALIDATED` when the recomputed
    `validation_errors` array is empty, and `BUILDING → FAILED` when it is non-empty"
    PRD §3.10: "On the `FAILED` branch, no item is frozen; the file's `status` becomes
    `FAILED`, the facility's posture is re-derived (this file no longer holds it `FROZEN`) and
    `Facility.version` advances by 1."

    Design: Difficulty/boundary_precision_check/boundary_precision_check__included_item_count_zero_vs_one_on_transparency_validate
    """
    s = setup_transparency_empty_chargemaster_scenario()
    tfile = build_transparency_file(
        s["facility"]["id"], s["facility"]["version"], file_format="CSV"
    )
    assert tfile["status"] == "BUILDING"
    assert tfile["as_of_datetime"].startswith("2026-08-01T00:00:00")
    assert tfile["included_item_count"] == 0
    assert tfile["total_gross_charge_cents"] == 0
    assert tfile["payer_column_count"] == 1, (
        "the single ACTIVE contract whose closed term contains the as-of instant is one column"
    )
    assert tfile["content_hash"] == _content_hash(), (
        "an empty inclusion set serializes to an empty string, whose SHA-256 digest is "
        f"{_content_hash()}: got {tfile['content_hash']}"
    )
    assert tfile["validation_errors"] == ["NO_PUBLISHABLE_ITEMS"], (
        "only the empty-inclusion string is assembled; the payer column exists, so "
        f"NO_ACTIVE_PAYER_COLUMNS must not appear: got {tfile['validation_errors']}"
    )
    assert read_facility(s["facility"]["id"])["chargemaster_posture"] == "FROZEN"

    failed = file_lifecycle(tfile["id"], "VALIDATE",
                            note="first attempt on an empty chargemaster")
    assert failed["status"] == "FAILED"
    assert read_file(tfile["id"])["status"] == "FAILED"
    assert read_facility(s["facility"]["id"])["chargemaster_posture"] == "OPEN", (
        "a FAILED file no longer holds the facility FROZEN"
    )


def test_exactly_one_publishable_item_carries_the_build_all_the_way_to_published():
    """PRD §3.10: "the inclusion set is evaluated at that instant: every `ChargeItem` of the
    file's facility whose `lifecycle_status` is `ACTIVE`, whose `price_status` is either
    `PRICED_CURRENT` or `PRICE_FROZEN`, and whose `duplicate_of_item_id` is null."
    PRD §3.10: "On the `VALIDATED` branch, every charge item of the facility whose
    `lifecycle_status` is `ACTIVE` and whose `price_status` is `PRICED_CURRENT` transitions to
    `PRICE_FROZEN` with each item's `version` advancing by 1, and the facility's posture is
    re-derived to `FROZEN` with `Facility.version` advancing by 1."
    PRD §3.10: "and `included_item_count` must be at least 1, otherwise
    `ERR_NO_PUBLISHABLE_ITEMS` (422). On success `status` becomes `PUBLISHED` and
    `published_at` takes the logical now."
    PRD §3.10: "Every charge item of the facility whose `price_status` is `PRICE_FROZEN` thaws
    back to `PRICED_CURRENT`, each advancing its own `version` by 1. And the facility records
    the outcome: `published_transparency_file_id` takes this file's identifier,
    `transparency_status` becomes `CURRENT`, `chargemaster_posture` is re-derived, and
    `Facility.version` advances by 1."

    Design: Difficulty/boundary_precision_check/boundary_precision_check__included_item_count_zero_vs_one_on_transparency_validate
    """
    s = setup_transparency_empty_chargemaster_scenario()
    first = build_transparency_file(
        s["facility"]["id"], s["facility"]["version"], file_format="CSV"
    )
    file_lifecycle(first["id"], "VALIDATE", note="first attempt on an empty chargemaster")

    item = create_active_item(
        s, cdm_number="CDM-6000", description="COMPREHENSIVE METABOLIC PANEL",
        code_type="CDM_INTERNAL", cost_basis_cents=40000,
        medicare_rate_cents=20000, market_p75_cents=200000,
    )
    assert read_item(item["id"])["gross_charge_cents"] == 128000

    facility = read_facility(s["facility"]["id"])
    second = build_transparency_file(facility["id"], facility["version"], file_format="CSV")
    assert second["included_item_count"] == 1
    assert second["total_gross_charge_cents"] == 128000
    assert second["payer_column_count"] == 1
    expected_hash = _content_hash("CDM-6000|0300||128000")
    assert second["content_hash"] == expected_hash, (
        "one row serializes as cdm_number, revenue code, empty code_value and gross charge "
        f"joined by bars: expected {expected_hash}, got {second['content_hash']}"
    )
    assert second["validation_errors"] == []

    validated = file_lifecycle(second["id"], "VALIDATE",
                               note="second attempt with exactly one publishable item")
    assert validated["status"] == "VALIDATED"
    assert read_item(item["id"])["price_status"] == "PRICE_FROZEN"
    assert read_facility(facility["id"])["chargemaster_posture"] == "FROZEN"

    published = file_lifecycle(second["id"], "PUBLISH", note="machine-readable file live")
    assert published["status"] == "PUBLISHED"
    assert published["published_at"].startswith("2026-08-01T00:00:00")
    assert read_item(item["id"])["price_status"] == "PRICED_CURRENT"

    final = read_facility(facility["id"])
    assert final["published_transparency_file_id"] == second["id"]
    assert final["transparency_status"] == "CURRENT"
    assert final["chargemaster_posture"] == "OPEN"
