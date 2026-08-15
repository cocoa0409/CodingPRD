"""Evidence upload/verify/supersede mechanics and the assurance-readiness
percentage that gates the UNDER_ASSURANCE transition."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId, create_approved_record, drive_cycle_to_locked, get_cycle,
    get_evidence_item, make_analyst_headers, make_collecting_cycle,
    make_factor, make_site, monthly_periods, recalc_inventory, sha256_hex,
    submit_record, transition_cycle, transition_payload, upload_evidence,
    upload_and_verify_evidence, validate_error, validate_paginated,
    validate_success, verify_evidence, verify_evidence_for_records,
)


def test_evidence_retention_and_supersede_chain(api, manager_headers, steward_headers):
    """PRD §3.4: "Each item enters `UPLOADED`, records the uploader's
    `X-User-ID` as `uploaded_by_user_id`, and computes its `retention_until`
    once, at creation, as December 31 of the parent cycle's `reporting_year`
    at 23:59:59 UTC plus seven years." and "The evidence list can be browsed
    by `activity_record_id`, by `supersedes_evidence_id`, or by `status`."

    Design: Corner/endpoints/evidence_upload_computes_retention_and_supersede_chain_visible
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle(reporting_year=2026)
    record = create_approved_record(
        cycle["id"], site["id"], factor["id"], quantity=100,
    )
    first = upload_evidence(record["id"], file_name="invoice-v1.pdf", sha256_hex=sha256_hex(1))
    retention = datetime.fromisoformat(first["retention_until"].replace("Z", "+00:00"))
    assert retention == datetime(2033, 12, 31, 23, 59, 59, tzinfo=timezone.utc), (
        "retention_until = 2026 cycle year end at 23:59:59 UTC plus seven years"
    )
    verify_evidence(first["id"])

    replacement = upload_evidence(
        record["id"], file_name="invoice-v2.pdf", sha256_hex=sha256_hex(2),
        supersedes_evidence_id=first["id"],
    )
    assert replacement["status"] == "UPLOADED"

    children, meta = validate_paginated(
        api.list_evidence_items(
            manager_headers, params={"supersedes_evidence_id": first["id"]}
        )
    )
    assert meta["total_count"] == 1 and len(children) == 1
    assert children[0]["id"] == replacement["id"], (
        "the supersedes_evidence_id filter returns exactly the replacement item"
    )


def test_supersede_drops_readiness_until_reverified(api, manager_headers, steward_headers):
    """PRD §3.4: "When the named item is currently `VERIFIED` and belongs to
    the same record, the upload drives it from `VERIFIED` to `SUPERSEDED` —
    supersession is performed by the upload itself, not by a separate
    transition — and the superseded item's version advances." and "Because
    the replacement enters `UPLOADED` and is uncovered until verified,
    `readiness_pct` is recomputed and may drop."

    Design: Corner/cross_cutting_layers/supersede_drops_readiness_until_reverified
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    record = create_approved_record(
        cycle["id"], site["id"], factor["id"], quantity=100,
    )
    first = upload_and_verify_evidence(record["id"], seed=11)
    assert get_cycle(cycle["id"])["readiness_pct"] == pytest.approx(100.0, abs=0.05), (
        "100 quantity approved and covered -> readiness 100.0"
    )

    replacement = upload_evidence(
        record["id"], file_name="invoice-v2.pdf", sha256_hex=sha256_hex(12),
        supersedes_evidence_id=first["id"],
    )
    assert replacement["status"] == "UPLOADED"
    assert get_evidence_item(first["id"])["status"] == "SUPERSEDED"
    assert get_cycle(cycle["id"])["readiness_pct"] == pytest.approx(0.0, abs=0.05), (
        "the replacement is uncovered until verified, so readiness drops to 0.0"
    )


def test_evidence_verify_reject_and_sod_guard(api, analyst_headers, steward_headers):
    """PRD §2.9: "The analyst verifying or rejecting an evidence item must
    not be the user recorded in its `uploaded_by_user_id`." PRD §3.4: "An
    analyst may instead reject an uploaded item — `UPLOADED` to `REJECTED` —
    under the same cycle gate and the same segregation rule."

    Design: Corner/state_machines/evidence_reject_and_sod_guard
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    record = submit_record(cycle["id"], site["id"], factor["id"], quantity=10)
    item = upload_evidence(record["id"])

    same_user = api.transition_evidence_item(
        item["id"], transition_payload("VERIFIED"), make_analyst_headers("steward-1")
    )
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    rejected = validate_success(
        api.transition_evidence_item(item["id"], transition_payload("REJECTED"), analyst_headers)
    )
    assert rejected["status"] == "REJECTED"


def _five_approved_records_with_evidence(cycle_id, site_id, factor_id, verified_count):
    """Five APPROVED records of 100 therm each on adjacent monthly periods,
    with VERIFIED evidence on the first `verified_count` of them."""
    periods = monthly_periods(2026, 5)
    records = []
    for start, end in periods:
        records.append(
            create_approved_record(
                cycle_id, site_id, factor_id, quantity=100,
                period_start=start, period_end=end,
            )
        )
    verify_evidence_for_records(records, verified_count, seed_start=200)
    return records


def test_readiness_below_80_blocks_assurance_then_80_passes(api, manager_headers):
    """PRD §3.2: "From `LOCKED`, the manager may begin assurance once
    `readiness_pct` is at least 80.0 — below that threshold the transition is
    refused with `ERR_READINESS_BELOW_THRESHOLD` — moving the cycle to
    `UNDER_ASSURANCE`." PRD §3.4: "It is the quantity-weighted share of the
    cycle's `APPROVED` records having at least one `VERIFIED` evidence item:
    the sum of `quantity` over covered approved records divided by the sum of
    `quantity` over all approved records, multiplied by 100, rounded half-up
    to one decimal place; with no approved records it is 0.0."

    Design: Difficulty/boundary_precision_check/readiness_threshold_exactly_80_passes
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    records = _five_approved_records_with_evidence(
        cycle["id"], site["id"], factor["id"], verified_count=3,
    )
    # 300 of 500 approved quantity covered -> readiness 60.0.
    recalc_inventory(cycle["id"])
    drive_cycle_to_locked(cycle["id"])

    blocked = api.transition_cycle(
        cycle["id"], transition_payload("UNDER_ASSURANCE"), manager_headers
    )
    validate_error(blocked, ApiErrorId.ERR_READINESS_BELOW_THRESHOLD, 422)

    # Reopen, verify one more record's evidence (400/500 = 80.0), re-lock.
    transition_cycle(cycle["id"], "UNDER_REVIEW")
    verify_evidence_for_records(records[3:4], 1, seed_start=300)
    readiness = get_cycle(cycle["id"])["readiness_pct"]
    assert readiness == pytest.approx(80.0, abs=0.05), (
        f"400/500 covered must read exactly 80.0, got {readiness}"
    )
    recalc_inventory(cycle["id"])
    transition_cycle(cycle["id"], "LOCKED")  # cycle already sits in UNDER_REVIEW
    assured_path = validate_success(
        api.transition_cycle(cycle["id"], transition_payload("UNDER_ASSURANCE"), manager_headers)
    )
    assert assured_path["status"] == "UNDER_ASSURANCE", (
        "exactly 80.0 satisfies the at-least-80.0 gate"
    )


def test_readiness_70_blocks_then_80_passes(api, manager_headers):
    """PRD §3.2: "From `LOCKED`, the manager may begin assurance once
    `readiness_pct` is at least 80.0 — below that threshold the transition is
    refused with `ERR_READINESS_BELOW_THRESHOLD` — moving the cycle to
    `UNDER_ASSURANCE`."

    Design: Difficulty/boundary_precision_check/readiness_threshold_exactly_80_passes
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    periods = monthly_periods(2026, 10)
    records = []
    for start, end in periods:
        records.append(
            create_approved_record(
                cycle["id"], site["id"], factor["id"], quantity=100,
                period_start=start, period_end=end,
            )
        )
    verify_evidence_for_records(records, 7, seed_start=400)
    # 700 of 1000 approved quantity covered -> readiness 70.0.
    assert get_cycle(cycle["id"])["readiness_pct"] == pytest.approx(70.0, abs=0.05)
    recalc_inventory(cycle["id"])
    drive_cycle_to_locked(cycle["id"])
    blocked = api.transition_cycle(
        cycle["id"], transition_payload("UNDER_ASSURANCE"), manager_headers
    )
    validate_error(blocked, ApiErrorId.ERR_READINESS_BELOW_THRESHOLD, 422)

    transition_cycle(cycle["id"], "UNDER_REVIEW")
    verify_evidence_for_records(records[7:8], 1, seed_start=500)
    assert get_cycle(cycle["id"])["readiness_pct"] == pytest.approx(80.0, abs=0.05)
    recalc_inventory(cycle["id"])
    transition_cycle(cycle["id"], "LOCKED")  # cycle already sits in UNDER_REVIEW
    passed = validate_success(
        api.transition_cycle(cycle["id"], transition_payload("UNDER_ASSURANCE"), manager_headers)
    )
    assert passed["status"] == "UNDER_ASSURANCE"
