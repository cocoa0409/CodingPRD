"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_farm(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["farm_number"], str) and data["farm_number"]
    assert isinstance(data["county_code"], str) and data["county_code"]
    assert isinstance(data["program_year"], int)
    assert data["farm_status"] in (
        "ACTIVE",
        "RECONSTITUTION_PENDING",
        "RECONSTITUTED",
        "RETIRED",
    )
    assert isinstance(data["total_base_acres"], (int, float))
    assert data["arc_co_ic_indicator"] in ("COUNTY", "INDIVIDUAL")


def assert_producer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["producer_name"], str) and data["producer_name"]
    assert isinstance(data["tax_id_last4"], str) and data["tax_id_last4"]
    assert data["entity_type"] in (
        "INDIVIDUAL",
        "CORPORATION",
        "PARTNERSHIP",
        "TRUST",
        "LLC",
    )
    assert data["agi_attestation_status"] in (
        "NOT_FILED",
        "FILED",
        "VERIFIED",
        "NONCOMPLIANT",
    )
    assert data["adjusted_gross_income"] is None or isinstance(
        data["adjusted_gross_income"], int
    )
    assert isinstance(data["payment_limitation_cap_cents"], int)
    assert data["conservation_status"] in (
        "CERTIFIED",
        "PENDING",
        "VIOLATION",
        "EXEMPT",
    )


def assert_membership(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("farm_id", ""))
    assert is_valid_uuid(data.get("producer_id", ""))
    assert isinstance(data["share_percent"], (int, float))
    assert isinstance(data["is_spouse_pair"], bool)
    assert data["membership_status"] in ("ACTIVE", "REMOVED")


def assert_tract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("farm_id", ""))
    assert isinstance(data["tract_number"], str) and data["tract_number"]
    assert isinstance(data["base_acres"], (int, float))
    assert isinstance(data["cropland_acres"], (int, float))
    assert data["tract_status"] in ("ACTIVE", "DIVIDED", "COMBINED")
    assert data.get("reconstituted_from_tract_id") is None or is_valid_uuid(
        data["reconstituted_from_tract_id"]
    )


def assert_field(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tract_id", ""))
    assert isinstance(data["field_number"], str) and data["field_number"]
    assert isinstance(data["acres"], (int, float))


def assert_acreage_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("farm_id", ""))
    assert isinstance(data["program_year"], int)
    assert data["report_status"] in (
        "DRAFT",
        "FILED",
        "CERTIFIED",
        "LATE_FILED",
        "REJECTED",
    )
    assert isinstance(data["reported_acres"], (int, float))
    assert data.get("filed_at") is None or is_iso8601_timestamp(data["filed_at"])


def assert_acreage_report_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("acreage_report_id", ""))
    assert is_valid_uuid(data.get("field_id", ""))
    assert isinstance(data["crop_code"], str) and data["crop_code"]
    assert isinstance(data["planted_acres"], (int, float))
    assert isinstance(data["prevented_planted_acres"], (int, float))
    assert data["intended_use"] in ("GRAIN", "SILAGE", "HAY", "GRAZE", "COVER")


def assert_program_election(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("farm_id", ""))
    assert isinstance(data["program_year"], int)
    assert isinstance(data["commodity"], str) and data["commodity"]
    assert data["election_code"] in ("PLC", "ARC_CO", "ARC_IC")
    assert data["election_status"] in ("ACTIVE", "SUPERSEDED", "WITHDRAWN", "LOCKED")


def assert_yield_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("farm_id", ""))
    assert isinstance(data["commodity"], str) and data["commodity"]
    assert isinstance(data["aph_yield_bu_per_acre"], (int, float))
    assert data["yield_status"] in ("PROVISIONAL", "UPDATED", "CERTIFIED", "LOCKED")
    assert isinstance(data["update_window_open"], bool)


def assert_yield_observation(data: dict):
    # PRD §2.4: YieldObservation carries ONLY id and created_at of the common
    # fields; both updated_at and version are absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "version" not in data, "YieldObservation must not carry version"
    assert "updated_at" not in data, "YieldObservation must not carry updated_at"
    assert is_valid_uuid(data.get("yield_record_id", ""))
    assert isinstance(data["crop_year"], int)
    assert data.get("actual_yield_bu_per_acre") is None or isinstance(
        data["actual_yield_bu_per_acre"], (int, float)
    )
    assert isinstance(data["is_disaster_substituted"], bool)


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("farm_id", ""))
    assert isinstance(data["program_year"], int)
    assert isinstance(data["commodity"], str) and data["commodity"]
    assert data["enrollment_status"] in (
        "DRAFT",
        "SUBMITTED",
        "CED_APPROVED",
        "CERTIFIED",
        "PAYMENT_COMPUTED",
        "PAYMENT_ISSUED",
        "ON_APPEAL",
        "REMANDED",
        "VOID",
    )
    assert data.get("pinned_election_id") is None or is_valid_uuid(
        data["pinned_election_id"]
    )
    assert data.get("pinned_yield_record_id") is None or is_valid_uuid(
        data["pinned_yield_record_id"]
    )
    assert data.get("computed_payment_cents") is None or isinstance(
        data["computed_payment_cents"], int
    )
    assert data.get("sequestration_cents") is None or isinstance(
        data["sequestration_cents"], int
    )


def assert_disaster_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("farm_id", ""))
    assert isinstance(data["program_year"], int)
    assert data["disaster_type"] in (
        "DROUGHT",
        "FLOOD",
        "HAIL",
        "FREEZE",
        "WILDFIRE",
        "EXCESS_MOISTURE",
    )
    assert data["application_status"] in (
        "DRAFT",
        "FILED",
        "UNDER_REVIEW",
        "APPROVED",
        "DENIED",
        "WITHDRAWN",
    )
    assert isinstance(data["loss_acres"], (int, float))
    assert isinstance(data["qualifying_commodity"], str) and data["qualifying_commodity"]
    assert isinstance(data["documentation_complete"], bool)


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("farm_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["appeal_status"] in (
        "FILED",
        "CED_REVIEW",
        "COMMITTEE_HEARING",
        "UPHELD",
        "REVERSED",
        "REMANDED",
        "CLOSED",
    )
    assert data["ground_code"] in (
        "FACTUAL_ERROR",
        "PROCEDURAL_ERROR",
        "MISAPPLICATION_OF_RULE",
        "NEW_EVIDENCE",
    )
    assert data.get("remands_appeal_id") is None or is_valid_uuid(
        data["remands_appeal_id"]
    )
    assert is_valid_uuid(data.get("filed_by_producer_id", ""))
    assert data.get("assigned_reviewer_producer_id") is None or is_valid_uuid(
        data["assigned_reviewer_producer_id"]
    )


def assert_payment_split_integrity(enrollment: dict):
    """Domain invariant (PRD §3.8): net computed_payment_cents is the
    post-limitation payment minus the 5.7% sequestration withholding, so
    computed + sequestration always reconstructs the post-limitation gross."""
    net = enrollment["computed_payment_cents"]
    seq = enrollment["sequestration_cents"]
    assert net is not None and seq is not None
    gross = net + seq
    assert gross >= 0
    # Sequestration is 5.7% of the post-limitation payment, rounded half-up to
    # two decimals; tolerance of one cent absorbs the rounding boundary.
    assert abs(round(gross * 0.057) - seq) <= 1
