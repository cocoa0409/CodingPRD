"""Entity assertions and domain invariant checkers for the Research Billing API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgingBucket,
    AmendmentScope,
    AmendmentStatus,
    AnalysisStatus,
    BillableTo,
    BillingHoldPosture,
    BillingState,
    BudgetCategory,
    BudgetStatus,
    CalendarStatus,
    ChargeSource,
    ExpectedRoutingTarget,
    FindingStatus,
    FindingType,
    HoldReason,
    IndIdeStatus,
    InvoiceStatus,
    ItemClassification,
    MedicareCoverageBasis,
    QctBasis,
    QctDetermination,
    RoutingState,
    RoutingTarget,
    StudyLifecycleStatus,
    SubjectStatus,
    SubjectVisitStatus,
)

STUDY_LEDGER_FIELDS = [
    "payer_billed_cents",
    "payer_refunded_cents",
    "sponsor_unbilled_cents",
    "sponsor_receivable_cents",
    "sponsor_collected_cents",
    "sponsor_written_off_cents",
    "improper_payer_exposure_cents",
    "delinquent_sponsor_cents",
]


def _values(enum_cls):
    return [member.value for member in enum_cls]


def _assert_identity(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601 UTC"


def _assert_full_identity(data: dict, label: str):
    """For the record types that carry updated_at and version as well."""
    _assert_identity(data, label)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_write_once_identity(data: dict, label: str):
    """A write-once record carries only id and created_at.

    Coverage items, calendar visits, and visit charge routes carry no
    ``updated_at`` and no ``version`` field at all.
    """
    _assert_identity(data, label)
    assert "version" not in data, f"{label} is write-once and must carry no version field"
    assert (
        "updated_at" not in data
    ), f"{label} is write-once and must carry no updated_at field"


# --------------------------------------------------------------------------
# Studies
# --------------------------------------------------------------------------


def assert_study(data: dict):
    _assert_full_identity(data, "study")
    assert isinstance(data["protocol_number"], str) and 1 <= len(
        data["protocol_number"]
    ) <= 40
    assert isinstance(data["title"], str)
    assert isinstance(data["sponsor_name"], str)
    assert data["funding_source"] in [
        "INDUSTRY_SPONSORED",
        "FEDERALLY_FUNDED",
        "INVESTIGATOR_INITIATED",
    ]
    assert data["ind_ide_status"] in _values(IndIdeStatus)
    assert isinstance(data["therapeutic_intent"], bool)
    assert data["lifecycle_status"] in _values(StudyLifecycleStatus)
    assert data["budget_status"] in _values(BudgetStatus)
    assert data["qct_determination"] in _values(QctDetermination)
    assert data["qct_basis"] is None or data["qct_basis"] in _values(QctBasis)
    assert data["billing_hold_posture"] in _values(BillingHoldPosture)
    for field in STUDY_LEDGER_FIELDS:
        assert isinstance(data[field], int), f"study.{field} must be an integer of cents"
        assert data[field] >= 0, f"study.{field} must not be negative"
    assert isinstance(data["open_finding_count"], int)
    assert isinstance(data["rebuild_required_calendar_count"], int)
    if data.get("registry_number") is not None:
        assert_registry_number(data["registry_number"])


def assert_registry_number(value: str):
    """Whenever it is non-null a registry number is NCT plus exactly eight digits."""
    assert isinstance(value, str), "registry_number must be a string when non-null"
    assert value.startswith("NCT"), f"registry_number must start with NCT, got {value}"
    digits = value[3:]
    assert len(digits) == 8 and digits.isdigit(), (
        f"registry_number must be NCT followed by exactly eight digits, got {value}"
    )


def assert_study_ledger_zeroed(data: dict):
    """A newly registered protocol opens with every ledger position at zero."""
    for field in STUDY_LEDGER_FIELDS:
        assert data[field] == 0, f"new study {field} must be 0, got {data[field]}"


def assert_payer_position_conserved(before: dict, after: dict):
    """payer_billed_cents plus payer_refunded_cents is unchanged by a refund."""
    before_total = before["payer_billed_cents"] + before["payer_refunded_cents"]
    after_total = after["payer_billed_cents"] + after["payer_refunded_cents"]
    assert before_total == after_total, (
        "the payer position (payer_billed_cents plus payer_refunded_cents) must be "
        f"unchanged by refunding a payer-billed charge: {before_total} -> {after_total}"
    )


def assert_sponsor_position_conserved(before: dict, after: dict):
    """sponsor_unbilled_cents plus sponsor_receivable_cents is unchanged."""
    before_total = before["sponsor_unbilled_cents"] + before["sponsor_receivable_cents"]
    after_total = after["sponsor_unbilled_cents"] + after["sponsor_receivable_cents"]
    assert before_total == after_total, (
        "the sponsor position (sponsor_unbilled_cents plus sponsor_receivable_cents) "
        f"must be unchanged: {before_total} -> {after_total}"
    )


def assert_posture(data: dict, expected: str):
    actual = data["billing_hold_posture"]
    assert actual == expected, (
        f"expected billing_hold_posture {expected}, got {actual} "
        f"(open_finding_count={data.get('open_finding_count')}, "
        f"rebuild_required_calendar_count={data.get('rebuild_required_calendar_count')}, "
        f"qct_determination={data.get('qct_determination')})"
    )


# --------------------------------------------------------------------------
# Coverage analyses and items
# --------------------------------------------------------------------------


def assert_coverage_analysis(data: dict):
    _assert_full_identity(data, "coverage_analysis")
    assert is_valid_uuid(data["study_id"])
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert data["status"] in _values(AnalysisStatus)
    assert isinstance(data["prepared_by_user_id"], str)
    assert isinstance(data["return_count"], int) and 0 <= data["return_count"] <= 2
    for counter in (
        "item_count",
        "routine_care_item_count",
        "research_paid_item_count",
        "promotional_item_count",
        "qct_conditional_item_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_analysis_counters(
    data: dict,
    item_count=None,
    routine_care_item_count=None,
    research_paid_item_count=None,
    promotional_item_count=None,
    qct_conditional_item_count=None,
):
    """Check whichever of the five classification counters the caller names."""
    expectations = {
        "item_count": item_count,
        "routine_care_item_count": routine_care_item_count,
        "research_paid_item_count": research_paid_item_count,
        "promotional_item_count": promotional_item_count,
        "qct_conditional_item_count": qct_conditional_item_count,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert data[field] == expected, (
                f"expected analysis {field} == {expected}, got {data[field]}"
            )


def assert_coverage_item(data: dict):
    assert_write_once_identity(data, "coverage_item")
    assert is_valid_uuid(data["coverage_analysis_id"])
    assert isinstance(data["item_code"], str)
    assert data["classification"] in _values(ItemClassification)
    assert data["medicare_coverage_basis"] in _values(MedicareCoverageBasis)
    assert data["budget_category"] in _values(BudgetCategory)
    assert data["billable_to"] in _values(BillableTo)
    assert data["charge_master_unit_cents"] >= 0
    assert data["negotiated_unit_cents"] >= 0
    assert data["units_per_occurrence"] >= 1
    assert data["expected_occurrences"] >= 0
    assert_billable_to_derived(data)


def assert_billable_to_derived(data: dict):
    """billable_to is derived from classification, never supplied."""
    expected = {
        "ROUTINE_CARE": "PAYER",
        "RESEARCH_PAID": "SPONSOR",
        "PROMOTIONAL": "NONE",
    }[data["classification"]]
    assert data["billable_to"] == expected, (
        f"a {data['classification']} item is billable to {expected}, "
        f"got {data['billable_to']}"
    )


# --------------------------------------------------------------------------
# Calendars, calendar visits and routes
# --------------------------------------------------------------------------


def assert_study_calendar(data: dict):
    _assert_full_identity(data, "study_calendar")
    assert is_valid_uuid(data["study_id"])
    assert is_valid_uuid(data["source_analysis_id"])
    assert isinstance(data["build_generation"], int) and data["build_generation"] >= 1
    assert data["status"] in _values(CalendarStatus)
    for counter in (
        "visit_count",
        "routed_item_count",
        "unrouted_per_patient_item_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    if data["status"] == "DRAFT":
        assert data["published_at"] is None, "a DRAFT calendar has published_at null"


def assert_calendar_visit(data: dict):
    assert_write_once_identity(data, "calendar_visit")
    assert is_valid_uuid(data["study_calendar_id"])
    assert isinstance(data["visit_name"], str)
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    for field in ("target_day_offset", "window_before_days", "window_after_days"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_visit_window_derived(data)


def assert_visit_window_derived(data: dict):
    """window_start_day is the target less the days before; window_end_day the target plus the days after."""
    expected_start = data["target_day_offset"] - data["window_before_days"]
    expected_end = data["target_day_offset"] + data["window_after_days"]
    assert data["window_start_day"] == expected_start, (
        f"window_start_day must be {expected_start}, got {data['window_start_day']}"
    )
    assert data["window_end_day"] == expected_end, (
        f"window_end_day must be {expected_end}, got {data['window_end_day']}"
    )


def assert_visit_charge_route(data: dict):
    assert_write_once_identity(data, "visit_charge_route")
    assert is_valid_uuid(data["calendar_visit_id"])
    assert is_valid_uuid(data["coverage_item_id"])
    assert isinstance(data["occurrences"], int) and data["occurrences"] >= 1
    assert data["routing_target"] in _values(RoutingTarget)
    assert isinstance(data["expected_amount_cents"], int)
    assert data["expected_amount_cents"] >= 0


# --------------------------------------------------------------------------
# Subjects and subject visits
# --------------------------------------------------------------------------


def assert_study_subject(data: dict):
    _assert_full_identity(data, "study_subject")
    assert is_valid_uuid(data["study_id"])
    assert isinstance(data["subject_number"], str)
    assert data["status"] in _values(SubjectStatus)
    assert isinstance(data["charge_count"], int) and data["charge_count"] >= 0


def assert_subject_visit(data: dict):
    _assert_full_identity(data, "subject_visit")
    assert is_valid_uuid(data["study_subject_id"])
    assert is_valid_uuid(data["calendar_visit_id"])
    assert isinstance(data["actual_service_date"], str)
    assert isinstance(data["day_offset_actual"], int)
    assert isinstance(data["calendar_generation_at_schedule"], int)
    assert data["status"] in _values(SubjectVisitStatus)
    assert isinstance(data["generated_charge_count"], int)


# --------------------------------------------------------------------------
# Charges
# --------------------------------------------------------------------------


def assert_charge(data: dict):
    _assert_full_identity(data, "charge")
    assert is_valid_uuid(data["study_id"])
    assert isinstance(data["charge_code"], str)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["source"] in _values(ChargeSource)
    assert data["routing_state"] in _values(RoutingState)
    assert data["billing_state"] in _values(BillingState)
    assert data["expected_routing_target"] in _values(ExpectedRoutingTarget)
    assert isinstance(data["improper_flag"], bool)
    assert data["hold_reason"] in _values(HoldReason)
    # The aging snapshot is refreshed only by the aging epoch, so a charge that
    # has never been through a run carries whatever the server opened it with.
    if data.get("aging_bucket") is not None:
        assert data["aging_bucket"] in _values(AgingBucket)
    if data.get("aging_days") is not None:
        assert isinstance(data["aging_days"], int) and data["aging_days"] >= 0
    assert_improper_flag_derived(data)


def assert_improper_flag_derived(data: dict):
    """improper_flag is true exactly when billing_state is BILLED_PAYER and
    expected_routing_target is anything other than PAYER."""
    expected = (
        data["billing_state"] == "BILLED_PAYER"
        and data["expected_routing_target"] != "PAYER"
    )
    assert data["improper_flag"] is expected, (
        "improper_flag must be true exactly when billing_state is BILLED_PAYER and "
        f"expected_routing_target is not PAYER: billing_state={data['billing_state']}, "
        f"expected_routing_target={data['expected_routing_target']}, "
        f"improper_flag={data['improper_flag']}"
    )


def assert_charge_states(data: dict, routing_state: str, billing_state: str):
    assert data["routing_state"] == routing_state, (
        f"expected routing_state {routing_state}, got {data['routing_state']}"
    )
    assert data["billing_state"] == billing_state, (
        f"expected billing_state {billing_state}, got {data['billing_state']}"
    )


def assert_aging_bucket_for_days(aging_days: int, aging_bucket: str):
    """CURRENT at 30 days or fewer, AGING_31_60 above 30 and at most 60,
    AGING_61_90 above 60 and at most 90, DELINQUENT_90_PLUS above 90."""
    if aging_days <= 30:
        expected = "CURRENT"
    elif aging_days <= 60:
        expected = "AGING_31_60"
    elif aging_days <= 90:
        expected = "AGING_61_90"
    else:
        expected = "DELINQUENT_90_PLUS"
    assert aging_bucket == expected, (
        f"{aging_days} days must fall in bucket {expected}, got {aging_bucket}"
    )


# --------------------------------------------------------------------------
# Sponsor invoices
# --------------------------------------------------------------------------


def assert_sponsor_invoice(data: dict):
    _assert_full_identity(data, "sponsor_invoice")
    assert is_valid_uuid(data["study_id"])
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["invoice_number"], str)
    assert data["status"] in _values(InvoiceStatus)
    assert isinstance(data["short_paid"], bool)
    for field in (
        "line_count",
        "subtotal_cents",
        "indirect_cents",
        "gross_total_cents",
        "volume_credit_cents",
        "net_total_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_invoice_number(data: dict, protocol_number: str):
    """INV-, then the protocol number, a hyphen, then the sequence number
    left-padded with zeros to three digits."""
    expected = f"INV-{protocol_number}-{data['sequence_number']:03d}"
    assert data["invoice_number"] == expected, (
        f"expected invoice_number {expected}, got {data['invoice_number']}"
    )


def assert_invoice_money(
    data: dict,
    line_count=None,
    subtotal_cents=None,
    indirect_cents=None,
    gross_total_cents=None,
    volume_credit_cents=None,
    net_total_cents=None,
):
    expectations = {
        "line_count": line_count,
        "subtotal_cents": subtotal_cents,
        "indirect_cents": indirect_cents,
        "gross_total_cents": gross_total_cents,
        "volume_credit_cents": volume_credit_cents,
        "net_total_cents": net_total_cents,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert data[field] == expected, (
                f"expected invoice {field} == {expected}, got {data[field]}"
            )
    assert data["gross_total_cents"] == data["subtotal_cents"] + data["indirect_cents"], (
        "gross_total_cents is subtotal_cents plus indirect_cents"
    )
    assert (
        data["net_total_cents"]
        == data["gross_total_cents"] - data["volume_credit_cents"]
    ), "net_total_cents is gross_total_cents less volume_credit_cents"


def assert_invoice_zeroed(data: dict):
    """A dispute zeroes every one of the invoice's own money fields."""
    for field in (
        "line_count",
        "subtotal_cents",
        "indirect_cents",
        "gross_total_cents",
        "volume_credit_cents",
        "net_total_cents",
    ):
        assert data[field] == 0, f"a disputed invoice returns {field} to zero, got {data[field]}"


# --------------------------------------------------------------------------
# Audit findings and amendments
# --------------------------------------------------------------------------


def assert_audit_finding(data: dict):
    _assert_full_identity(data, "audit_finding")
    assert is_valid_uuid(data["study_id"])
    assert data["finding_type"] in _values(FindingType)
    assert data["status"] in _values(FindingStatus)
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] >= 0
    assert isinstance(data["refund_amount_cents"], int)
    assert isinstance(data["opened_by_user_id"], str)


def assert_amendment(data: dict):
    _assert_full_identity(data, "amendment")
    assert is_valid_uuid(data["study_id"])
    assert isinstance(data["amendment_number"], int) and data["amendment_number"] >= 1
    assert data["scope"] in _values(AmendmentScope)
    assert data["status"] in _values(AmendmentStatus)
    assert isinstance(data["reanalysis_required"], bool)
    assert isinstance(data["calendar_rebuild_required"], bool)
    assert_amendment_flags_derived(data)


def assert_amendment_flags_derived(data: dict):
    """reanalysis_required is true for every scope other than ADMINISTRATIVE;
    calendar_rebuild_required only for the two schedule-touching scopes."""
    scope = data["scope"]
    expected_reanalysis = scope != "ADMINISTRATIVE"
    expected_rebuild = scope in ("VISIT_SCHEDULE_CHANGE", "ITEM_AND_SCHEDULE_CHANGE")
    assert data["reanalysis_required"] is expected_reanalysis, (
        f"scope {scope} implies reanalysis_required {expected_reanalysis}"
    )
    assert data["calendar_rebuild_required"] is expected_rebuild, (
        f"scope {scope} implies calendar_rebuild_required {expected_rebuild}"
    )


# --------------------------------------------------------------------------
# Computed reads
# --------------------------------------------------------------------------


def assert_charge_review_summary(data: dict):
    assert is_valid_uuid(data["study_id"])
    assert data["billing_hold_posture"] in _values(BillingHoldPosture)
    assert isinstance(data["unrouted_charge_count"], int)
    for field in (
        "sponsor_unbilled_cents",
        "sponsor_receivable_cents",
        "payer_billed_cents",
        "payer_refunded_cents",
        "improper_payer_exposure_cents",
        "delinquent_sponsor_cents",
        "open_finding_count",
    ):
        assert isinstance(data[field], int), f"summary.{field} must be an integer"


def assert_summary_matches_study(summary: dict, study: dict):
    """The dashboard is a computed read over the same derived ledger."""
    for field in (
        "billing_hold_posture",
        "sponsor_unbilled_cents",
        "sponsor_receivable_cents",
        "payer_billed_cents",
        "payer_refunded_cents",
        "improper_payer_exposure_cents",
        "delinquent_sponsor_cents",
        "open_finding_count",
    ):
        assert summary[field] == study[field], (
            f"summary.{field} ({summary[field]}) must match the study's "
            f"{field} ({study[field]})"
        )
