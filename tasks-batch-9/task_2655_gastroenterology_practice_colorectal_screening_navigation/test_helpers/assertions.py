"""Entity assertions and domain invariant checkers."""
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_resource_fields(data: dict, entity: str = "resource") -> None:
    """Every resource carries a server-minted UUID `id` with no type prefix, an ISO
    8601 `created_at`, an `updated_at` in the same format, and an integer `version`
    that starts at 1 (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID string with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC instant, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC instant, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer of at least 1, got {data.get('version')!r}"
    )


def assert_insurance_plan(data: dict) -> None:
    assert_common_resource_fields(data, "InsurancePlan")
    assert isinstance(data["plan_code"], str) and 1 <= len(data["plan_code"]) <= 32
    assert isinstance(data["payer_name"], str) and len(data["payer_name"]) > 0
    assert 0.0 <= float(data["preventive_coverage_pct"]) <= 1.0
    assert 0.0 <= float(data["diagnostic_coinsurance_pct"]) <= 1.0
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert isinstance(data["out_of_pocket_max_cents"], int)
    assert data["out_of_pocket_max_cents"] >= 0
    assert data["polypectomy_carveout"] in ("PREVENTIVE_RETAINED", "DIAGNOSTIC_CONVERTED")
    assert isinstance(data["modifier_33_honored"], bool)
    assert isinstance(data["anesthesia_bundled"], bool)


def assert_clinician(data: dict) -> None:
    assert_common_resource_fields(data, "Clinician")
    assert isinstance(data["npi"], str) and 1 <= len(data["npi"]) <= 20
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["clinician_type"] in ("ENDOSCOPIST", "ANESTHESIA")
    assert 1 <= data["max_overlapping_rooms"] <= 4
    assert 0.0 <= float(data["adr_benchmark_pct"]) <= 1.0
    assert data["credential_status"] in ("ACTIVE", "SUSPENDED")


def assert_patient(data: dict) -> None:
    assert_common_resource_fields(data, "Patient")
    assert isinstance(data["mrn"], str) and 1 <= len(data["mrn"]) <= 32
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) == 10
    assert is_valid_uuid(data["insurance_plan_id"])
    assert data["risk_tier"] in ("AVERAGE", "INCREASED", "HIGH")
    assert 1 <= data["asa_class"] <= 5
    assert data["deductible_applied_cents"] >= 0
    assert data["oop_applied_cents"] >= 0
    assert data["open_episode_count"] >= 0
    assert data["navigation_priority"] in ("ROUTINE", "HIGH")
    assert_patient_priority_invariant(data)


def assert_patient_priority_invariant(data: dict) -> None:
    """`navigation_priority` becomes `HIGH` whenever `open_episode_count` reaches two
    or more and returns to `ROUTINE` whenever the count falls below two (PRD §3.1)."""
    expected = "HIGH" if data["open_episode_count"] >= 2 else "ROUTINE"
    assert data["navigation_priority"] == expected, (
        f"navigation_priority must be {expected} at open_episode_count "
        f"{data['open_episode_count']}, got {data['navigation_priority']}"
    )


def assert_endoscopy_session(data: dict) -> None:
    assert_common_resource_fields(data, "EndoscopySession")
    assert isinstance(data["room_code"], str) and len(data["room_code"]) > 0
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert is_valid_uuid(data["lead_endoscopist_id"])
    assert data["anesthesia_mode"] in ("MODERATE_SEDATION", "MAC")
    assert 0 <= data["turnover_minutes"] <= 60
    assert 1 <= data["max_procedures"] <= 20
    assert data["status"] in (
        "DRAFT", "PUBLISHED", "COVERAGE_CONFIRMED", "SUSPENDED", "CLOSED",
    )
    assert_session_minute_ledger(data)


def assert_session_minute_ledger(data: dict) -> None:
    """`remaining_minutes` is `capacity_minutes` less `booked_minutes`, and the
    invariant that booked and remaining minutes sum to capacity holds at every
    observable instant (PRD §3.7)."""
    assert isinstance(data["capacity_minutes"], int)
    assert isinstance(data["booked_minutes"], int)
    assert isinstance(data["remaining_minutes"], int)
    assert data["booked_minutes"] + data["remaining_minutes"] == data["capacity_minutes"], (
        f"booked_minutes {data['booked_minutes']} + remaining_minutes "
        f"{data['remaining_minutes']} must equal capacity_minutes "
        f"{data['capacity_minutes']}"
    )


def assert_anesthesia_coverage(data: dict) -> None:
    assert_common_resource_fields(data, "AnesthesiaCoverage")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["anesthesia_clinician_id"])
    assert is_iso8601_timestamp(data["coverage_start_utc"])
    assert is_iso8601_timestamp(data["coverage_end_utc"])
    assert isinstance(data["covers_full_window"], bool)
    assert isinstance(data["overlap_index"], int) and data["overlap_index"] >= 1
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_referral(data: dict) -> None:
    assert_common_resource_fields(data, "Referral")
    assert is_valid_uuid(data["patient_id"])
    assert data["reason"] in (
        "AVERAGE_RISK_SCREENING", "FAMILY_HISTORY", "POSITIVE_FIT",
        "SURVEILLANCE", "SYMPTOMATIC_BLEEDING",
    )
    assert 1 <= data["asa_class_reported"] <= 5
    assert isinstance(data["anticoagulant_reported"], bool)
    assert data["status"] in (
        "SUBMITTED", "UNDER_TRIAGE", "INFO_REQUESTED",
        "ACCEPTED_OPEN_ACCESS", "ACCEPTED_OFFICE_VISIT", "DECLINED",
    )
    assert data["risk_screen_result"] in (
        "PENDING", "CLEARED_OPEN_ACCESS", "OFFICE_VISIT_REQUIRED",
    )
    assert 0 <= data["info_request_rounds"] <= 2


def assert_screening_episode(data: dict) -> None:
    assert_common_resource_fields(data, "ScreeningEpisode")
    assert is_valid_uuid(data["patient_id"])
    assert data["indication"] in (
        "SCREENING_AVERAGE_RISK", "SCREENING_HIGH_RISK",
        "SURVEILLANCE", "DIAGNOSTIC_FOLLOWUP",
    )
    assert data["origin"] in (
        "DIRECT", "REFERRAL", "NONINVASIVE_POSITIVE", "SURVEILLANCE_RECALL",
    )
    assert data["eligibility_status"] in (
        "ELIGIBLE", "INELIGIBLE_AGE", "INELIGIBLE_PRIOR_CRC", "INELIGIBLE_RISK_MISMATCH",
    )
    assert data["risk_tier_snapshot"] in ("AVERAGE", "INCREASED", "HIGH")
    assert data["clinical_status"] in (
        "OPEN", "PROCEDURE_SCHEDULED", "PATHOLOGY_PENDING",
        "CLOSED_SURVEILLANCE_SET", "CLOSED_DECLINED", "CLOSED_SUPERSEDED",
    )
    assert data["navigation_status"] in (
        "NOT_STARTED", "OUTREACH_ACTIVE", "PREP_AT_RISK",
        "PREP_CONFIRMED", "NAVIGATION_COMPLETE",
    )
    assert data["prep_attestation"] in ("NONE", "COMPLETED", "NOT_COMPLETED")
    assert isinstance(data["outreach_log"], list)
    assert_prep_score_bounds(data["prep_adherence_score"])
    assert len(data["index_date"]) == 10
    assert len(data["due_date"]) == 10


def assert_prep_score_bounds(score) -> None:
    """The sum is clamped into the range 0.00 through 10.00 inclusive and rounded
    half-up to two decimal places (PRD §3.5)."""
    value = float(score)
    assert 0.00 <= value <= 10.00, f"prep_adherence_score {value} outside 0.00-10.00"
    assert round(value, 2) == value, (
        f"prep_adherence_score {value} carries more than two decimal places"
    )


def assert_noninvasive_test(data: dict) -> None:
    assert_common_resource_fields(data, "NoninvasiveTest")
    assert is_valid_uuid(data["episode_id"])
    assert data["test_type"] in ("FIT", "MT_SDNA")
    assert len(data["collected_date"]) == 10
    assert data["result"] in ("PENDING", "NEGATIVE", "POSITIVE", "INSUFFICIENT_SPECIMEN")
    if data["result"] == "PENDING":
        assert data["resulted_at"] is None
    else:
        assert is_iso8601_timestamp(data["resulted_at"])


def assert_procedure_booking(data: dict) -> None:
    assert_common_resource_fields(data, "ProcedureBooking")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["episode_id"])
    assert is_valid_uuid(data["performing_endoscopist_id"])
    assert is_iso8601_timestamp(data["slot_start_utc"])
    assert is_iso8601_timestamp(data["slot_end_utc"])
    assert is_iso8601_timestamp(data["occupancy_end_utc"])
    assert 15 <= data["duration_minutes"] <= 120
    assert data["status"] in (
        "BOOKED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED",
        "ABORTED_INADEQUATE_PREP", "CANCELLED",
    )
    assert isinstance(data["released_minutes"], int) and data["released_minutes"] >= 0


def assert_pathology_report(data: dict) -> None:
    assert_common_resource_fields(data, "PathologyReport")
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["accession_number"], str)
    assert 1 <= len(data["accession_number"]) <= 32
    assert isinstance(data["specimens"], list)
    assert isinstance(data["high_grade_dysplasia"], bool)
    assert data["status"] in ("RECEIVED", "FINALIZED", "AMENDED")
    assert data["amendment_count"] >= 0
    assert_pathology_findings_derived(data)


def assert_pathology_findings_derived(data: dict) -> None:
    """The five findings fields are derived from `specimens` (PRD §3.8):
    `adenoma_count` counts TUBULAR_ADENOMA and TUBULOVILLOUS_ADENOMA,
    `sessile_serrated_count` counts SESSILE_SERRATED_LESION, `largest_adenoma_mm`
    is the greatest `size_mm` among the adenoma specimens and 0 when there are
    none, `villous_component` is true when any specimen is TUBULOVILLOUS_ADENOMA,
    and `adenocarcinoma_present` is true when any specimen is ADENOCARCINOMA."""
    specimens = data["specimens"]
    adenomas = [s for s in specimens
                if s["histology"] in ("TUBULAR_ADENOMA", "TUBULOVILLOUS_ADENOMA")]
    assert data["adenoma_count"] == len(adenomas), (
        f"adenoma_count must be {len(adenomas)}, got {data['adenoma_count']}"
    )
    sessile = [s for s in specimens if s["histology"] == "SESSILE_SERRATED_LESION"]
    assert data["sessile_serrated_count"] == len(sessile)
    expected_largest = max((s["size_mm"] for s in adenomas), default=0)
    assert data["largest_adenoma_mm"] == expected_largest, (
        f"largest_adenoma_mm must be {expected_largest}, got {data['largest_adenoma_mm']}"
    )
    assert data["villous_component"] is any(
        s["histology"] == "TUBULOVILLOUS_ADENOMA" for s in specimens
    )
    assert data["adenocarcinoma_present"] is any(
        s["histology"] == "ADENOCARCINOMA" for s in specimens
    )


def assert_surveillance_recommendation(data: dict) -> None:
    assert_common_resource_fields(data, "SurveillanceRecommendation")
    assert is_valid_uuid(data["episode_id"])
    assert data["basis"] in ("GUIDELINE", "OVERRIDE_ATTESTED")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert isinstance(data["computed_interval_months"], int)
    assert isinstance(data["assigned_interval_months"], int)
    assert data["computed_interval_months"] >= 6
    assert len(data["next_due_date"]) == 10
    if data["basis"] == "GUIDELINE":
        assert data["attesting_endoscopist_id"] is None
        assert data["assigned_interval_months"] == data["computed_interval_months"]
    else:
        assert is_valid_uuid(data["attesting_endoscopist_id"])


def assert_billing_claim(data: dict) -> None:
    assert_common_resource_fields(data, "BillingClaim")
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["insurance_plan_id"])
    assert data["status"] in (
        "PROVISIONAL_PRICED", "REPRICED", "FINALIZED", "DISPUTED", "VOIDED",
    )
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["classification"] in ("SCREENING_PREVENTIVE", "DIAGNOSTIC")
    assert isinstance(data["line_items"], list)
    assert data["reprice_count"] >= 0
    for field in ("base_allowed_cents", "allowed_amount_cents",
                  "deductible_applied_cents", "coinsurance_cents",
                  "patient_responsibility_cents", "plan_paid_cents"):
        assert isinstance(data[field], int), (
            f"{field} must be integer cents, got {data[field]!r}"
        )
        assert data[field] >= 0


def assert_claim_money_identity(data: dict) -> None:
    """`plan_paid_cents` is `allowed_amount_cents` less `patient_responsibility_cents`
    (PRD §3.9)."""
    assert (data["allowed_amount_cents"] - data["patient_responsibility_cents"]
            == data["plan_paid_cents"]), (
        f"allowed_amount_cents {data['allowed_amount_cents']} less "
        f"patient_responsibility_cents {data['patient_responsibility_cents']} must "
        f"equal plan_paid_cents {data['plan_paid_cents']}"
    )


def assert_line_items_ordered(data: dict) -> None:
    """`line_items` is an ordered array in exactly the order facility, professional,
    anesthesia (PRD §3.9), unless the abort override replaced the whole schedule."""
    codes = [line["code"] for line in data["line_items"]]
    if codes == ["ABORTED_TECHNICAL"] or codes == []:
        return
    expected_prefix = ["FACILITY", "PROFESSIONAL", "ANESTHESIA"][: len(codes)]
    assert codes == expected_prefix, (
        f"line_items must be ordered {expected_prefix}, got {codes}"
    )


def assert_quality_period(data: dict) -> None:
    assert_common_resource_fields(data, "QualityPeriod")
    assert is_valid_uuid(data["endoscopist_id"])
    assert len(data["period_start_date"]) == 10
    assert len(data["period_end_date"]) == 10
    assert data["attribution_basis"] in ("PROCEDURE_DATE", "PATHOLOGY_FINALIZATION_DATE")
    assert data["status"] in ("OPEN", "LOCKED", "ATTESTED")
    assert data["screening_colonoscopy_count"] >= 0
    assert data["adenoma_positive_count"] >= 0
    assert isinstance(data["remediation_required"], bool)
    if data["benchmark_result"] is not None:
        assert data["benchmark_result"] in ("INSUFFICIENT_VOLUME", "MET", "MISSED")


def assert_adr_precision(adr_pct: Optional[float]) -> None:
    """An adenoma detection rate is a number with four decimal places, rounded
    half-up, and it is `null` rather than zero when its denominator is zero
    (PRD §2.8)."""
    if adr_pct is None:
        return
    value = float(adr_pct)
    assert round(value, 4) == value, (
        f"adr_pct {value} carries more than four decimal places"
    )
    assert 0.0 <= value <= 1.0


def assert_error_envelope(body: dict) -> None:
    """Error responses carry `response_type` 'error' and a `data` object holding
    `error_id` and `message` (PRD §2.2)."""
    assert body.get("response_type") == "error"
    assert set(("error_id", "message")).issubset(body["data"].keys())
    assert isinstance(body["data"]["message"], str)
    assert len(body["data"]["message"].strip()) > 0


def assert_utc_instant(value: str, expected_second_precision: str) -> None:
    """Compare a stored UTC instant against an expected value given to the second.

    Timestamps are never taken from wall-clock time; the logical clock is the sole
    source of every stamped instant (PRD §2.4). The comparison is made on the instant
    itself so that the fractional-second rendering of the envelope is not conflated
    with the value the specification derives.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{value!r} is not an ISO 8601 UTC instant"
    assert value[:19] == expected_second_precision, (
        f"Expected instant {expected_second_precision}, got {value}"
    )
