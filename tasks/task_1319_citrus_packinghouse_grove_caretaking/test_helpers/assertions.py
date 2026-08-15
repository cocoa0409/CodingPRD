"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}: created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}: updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}: version must be a positive integer"


def assert_grower(data):
    _assert_common_fields(data, "Grower")
    assert isinstance(data["grower_code"], str) and data["grower_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["advance_outstanding_cents"], int)
    assert isinstance(data["caretaking_balance_cents"], int)


def assert_grove(data):
    _assert_common_fields(data, "Grove")
    assert data["variety"] in ("HAMLIN", "VALENCIA", "RED_GRAPEFRUIT", "TANGERINE")
    assert data["acreage"] > 0
    assert isinstance(data["block_code"], str) and data["block_code"]
    assert isinstance(data["county_code"], str) and data["county_code"]
    assert data["lifecycle_status"] in ("PRODUCTIVE", "RETIRED")
    assert data["quarantine_posture"] in ("CLEAR", "QUARANTINED")


def assert_maturity_test(data):
    _assert_common_fields(data, "MaturityTest")
    assert data["brix"] > 0 and data["acid_pct"] > 0
    assert 0 < data["juice_pct"] <= 100
    assert data["result"] in ("PASS", "FAIL")
    assert data["status"] in ("CURRENT", "SUPERSEDED")
    assert is_iso8601_timestamp(data["sampled_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    # ratio carries exactly 2 decimal places (PRD §2.7)
    assert abs(round(data["ratio"], 2) - data["ratio"]) < 1e-9


def assert_crew(data):
    _assert_common_fields(data, "HarvestCrew")
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert data["daily_capacity_boxes"] > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_assignment(data):
    _assert_common_fields(data, "HarvestAssignment")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["planned_boxes"] > 0
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_delivery(data):
    _assert_common_fields(data, "Delivery")
    assert data["gross_boxes"] > 0
    assert 0 <= data["tare_boxes"] < data["gross_boxes"]
    assert data["net_boxes"] == data["gross_boxes"] - data["tare_boxes"]
    assert data["processing_status"] in (
        "RECEIVED", "IN_DEGREENING", "READY_TO_SORT", "SORTED", "CLOSED")
    assert data["regulatory_status"] in ("CLEAR", "HELD", "RELEASED", "CONDEMNED")
    assert data["variety"] in ("HAMLIN", "VALENCIA", "RED_GRAPEFRUIT", "TANGERINE")
    assert data["requires_degreening"] == (
        data["variety"] in ("RED_GRAPEFRUIT", "TANGERINE"))


def assert_room(data):
    _assert_common_fields(data, "DegreeningRoom")
    assert data["capacity_boxes"] > 0
    assert data["min_hours"] <= data["max_hours"]
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")


def assert_session(data):
    _assert_common_fields(data, "DegreeningSession")
    assert data["boxes"] > 0
    assert data["planned_hours"] > 0
    assert data["status"] in ("CONDITIONING", "RELEASED", "ABORTED")
    assert is_iso8601_timestamp(data["started_at"])


def assert_sort_run(data):
    _assert_common_fields(data, "SortRun")
    for field in ("fancy_boxes", "choice_boxes", "standard_boxes",
                  "juice_boxes", "cull_boxes"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert 1 <= data["color_score"] <= 10
    assert 0 <= data["defect_pct"] <= 100
    assert data["status"] in ("OPEN", "VERIFIED", "POSTED", "VOIDED")
    # ge_boxes carries exactly 2 decimal places (PRD §2.7)
    assert abs(round(data["ge_boxes"], 2) - data["ge_boxes"]) < 1e-9


def assert_channel(data):
    _assert_common_fields(data, "AllocationChannel")
    assert data["channel_type"] in ("EXPORT", "DOMESTIC_FRESH", "JUICE")
    assert data["destination_market"] in ("JAPAN", "EU", "KOREA", "DOMESTIC", "NONE")
    assert data["price_cents_per_box"] > 0
    assert isinstance(data["accepts_grades"], list)


def assert_pool(data):
    _assert_common_fields(data, "Pool")
    assert data["variety"] in ("HAMLIN", "VALENCIA", "RED_GRAPEFRUIT", "TANGERINE")
    assert data["status"] in ("OPEN", "INTAKE_CLOSED", "PRICED", "SETTLED")
    assert isinstance(data["posted_proceeds_cents"], int)
    assert isinstance(data["sorted_field_boxes"], int)
    assert abs(round(data["posted_ge_boxes"], 2) - data["posted_ge_boxes"]) < 1e-9
    assert isinstance(data["provisional_price_cents_per_ge_box"], int)


def assert_advance(data):
    _assert_common_fields(data, "AdvancePayment")
    assert data["amount_cents"] > 0
    assert data["recoup_policy"] in ("NEXT_SETTLEMENT_FULL", "PRO_RATA_THIRDS")
    assert data["status"] in (
        "REQUESTED", "ISSUED", "DENIED", "PARTIALLY_RECOUPED", "RECOUPED", "WRITTEN_OFF")
    assert_advance_invariants(data)


def assert_advance_invariants(data):
    """PRD §3.6: amount always equals recouped + written_off + outstanding."""
    assert data["amount_cents"] == (
        data["recouped_cents"] + data["written_off_cents"] + data["outstanding_cents"]), (
        f"advance money partition broken: {data['amount_cents']} != "
        f"{data['recouped_cents']} + {data['written_off_cents']} + {data['outstanding_cents']}")


def assert_service_order(data):
    _assert_common_fields(data, "CaretakingServiceOrder")
    assert data["service_type"] in ("SPRAY", "FERTILIZE", "PRUNE", "MOW")
    assert data["acres_treated"] > 0
    assert data["status"] in ("REQUESTED", "SCHEDULED", "COMPLETED", "INVOICED", "CANCELLED")


def assert_invoice(data):
    _assert_common_fields(data, "CaretakingInvoice")
    assert isinstance(data["line_order_ids"], list)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "DISPUTED", "VOID")


def assert_quarantine_order(data):
    _assert_common_fields(data, "QuarantineOrder")
    assert data["scope_type"] in ("GROVE", "COUNTY_ZONE")
    assert data["pest_type"] in ("CANKER", "HLB_GREENING", "FRUIT_FLY", "BLACK_SPOT")
    assert data["status"] in ("ACTIVE", "RELEASED")
    assert is_iso8601_timestamp(data["issued_at"])


def assert_export_lot(data):
    _assert_common_fields(data, "ExportLot")
    assert data["destination_market"] in ("JAPAN", "EU", "KOREA")
    assert data["grade"] in ("FANCY", "CHOICE", "STANDARD")
    assert data["boxes"] > 0
    assert data["status"] in (
        "BUILDING", "INSPECTION_READY", "CERTIFIED", "REJECTED", "SHIPPED", "DIVERTED")


def assert_certificate(data):
    _assert_common_fields(data, "PhytosanitaryCertificate")
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert data["inspection_result"] in ("PASS", "FAIL")
    assert data["status"] in ("ISSUED", "CONSUMED", "REVOKED")
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def allocation_boxes_per_channel(allocation, channel_id_by_code=None):
    """Aggregate allocation lines into {channel_ref: total_boxes}.

    The PRD pins the waterfall's per-channel totals and proceeds but leaves the
    juice line's grade granularity open, so tests compare per-channel totals.
    `channel_id_by_code` maps channel_code -> channel id when the assertion is
    expressed in human-readable channel codes.
    """
    totals = {}
    for line in allocation or []:
        ref = line.get("channel_id", line.get("channel"))
        if channel_id_by_code and ref in channel_id_by_code:
            ref = ref  # already resolved
        boxes = line.get("boxes", line.get("box_count"))
        totals[ref] = totals.get(ref, 0) + boxes
    return totals


def statement_amounts(statement):
    """Extract (share, offset, recouped, paid) from a settlement statement row,
    tolerating the field-name freedom the PRD leaves open (§3.6 describes the
    statement contents as share, offset, recoupment, and amount paid)."""
    def pick(*names):
        for name in names:
            if name in statement and statement[name] is not None:
                return statement[name]
        raise AssertionError(
            f"settlement statement lacks any of {names}: keys={sorted(statement)}")
    share = pick("share", "share_cents")
    offset = pick("offset", "offset_cents", "caretaking_offset", "caretaking_offset_cents")
    recouped = pick("recoup", "recouped", "recoup_cents", "recouped_cents",
                    "recoupment", "recoupment_cents")
    paid = pick("paid", "paid_cents", "payment", "payment_cents", "amount_paid_cents")
    return share, offset, recouped, paid
