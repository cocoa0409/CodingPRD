"""Entity assertions and domain invariant checkers (PRD §2.2–§2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str, with_version: bool = True):
    assert isinstance(data, dict), f"{entity} payload must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"{entity}.updated_at must be ISO 8601"
        assert isinstance(
            data.get("version"), int
        ), f"{entity}.version must be an integer"
        assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_title(data: dict):
    _assert_common(data, "Title")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("author"), str) and len(data["author"]) > 0
    assert data.get("title_kind") in ("PLAY", "MUSICAL", "MUSICAL_WITH_SCORE")
    assert data.get("royalty_basis") in (
        "PER_PERFORMANCE",
        "GROSS_PERCENT",
        "HYBRID",
    )
    for field in (
        "base_flat_fee_cents",
        "gross_percent_bp",
        "perusal_fee_cents",
        "rental_deposit_cents",
        "late_fee_per_day_cents",
        "restricted_late_fee_per_day_cents",
        "recording_royalty_flat_cents",
    ):
        assert isinstance(data.get(field), int), f"Title.{field} must be int cents"
    assert isinstance(data.get("restricted_material"), bool)
    assert data.get("status") in ("ACTIVE", "WITHDRAWN")


def assert_territory_restriction(data: dict):
    _assert_common(data, "TerritoryRestriction")
    assert isinstance(data.get("title_id"), str)
    assert isinstance(data.get("territory_code"), str)
    assert data.get("restriction_kind") in (
        "BLACKOUT",
        "EXCLUSIVE_RUN",
        "PRO_TOUR_OVERLAP",
    )
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data.get("blocks_classification") in ("AMATEUR", "PROFESSIONAL", "BOTH")
    assert isinstance(data.get("active"), bool)


def assert_organization(data: dict):
    _assert_common(data, "Organization")
    assert isinstance(data.get("legal_name"), str) and len(data["legal_name"]) > 0
    assert data.get("org_kind") in (
        "SCHOOL",
        "COMMUNITY",
        "SEMI_PRO",
        "PROFESSIONAL_COMPANY",
    )
    assert isinstance(data.get("home_territory_code"), str)
    assert data.get("standing") in ("GOOD", "SUSPENDED")


def assert_application(data: dict):
    _assert_common(data, "LicenseApplication")
    assert is_valid_uuid(data.get("title_id", ""))
    assert is_valid_uuid(data.get("organization_id", ""))
    assert isinstance(data.get("requested_territory_code"), str)
    assert data.get("requested_classification") in ("AMATEUR", "PROFESSIONAL")
    assert isinstance(data.get("venue_seating_capacity"), int)
    assert data["venue_seating_capacity"] >= 1
    assert isinstance(data.get("ticket_top_price_cents"), int)
    assert isinstance(data.get("performers_compensated"), bool)
    assert isinstance(data.get("admission_charged"), bool)
    assert isinstance(data.get("projected_gross_cents"), int)
    assert isinstance(data.get("performance_count"), int)
    assert data["performance_count"] >= 1
    assert is_iso8601_timestamp(data.get("first_performance_date", ""))
    assert is_iso8601_timestamp(data.get("last_performance_date", ""))
    assert data.get("status") in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "RETURNED_FOR_INFO",
        "APPROVED",
        "REJECTED",
    )
    assert isinstance(data.get("review_round"), int)
    assert data["review_round"] >= 0


def assert_agreement(data: dict):
    _assert_common(data, "LicenseAgreement")
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("title_id", ""))
    assert is_valid_uuid(data.get("organization_id", ""))
    assert isinstance(data.get("territory_code"), str)
    assert data.get("classification") in ("AMATEUR", "PROFESSIONAL")
    assert isinstance(data.get("house_seating_capacity"), int)
    assert isinstance(data.get("contracted_performance_count"), int)
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data.get("royalty_mode") in ("QUOTED", "SETTLED")
    assert isinstance(data.get("quoted_royalty_total_cents"), int)
    assert data.get("settled_royalty_total_cents") is None or isinstance(
        data["settled_royalty_total_cents"], int
    )
    assert isinstance(data.get("royalty_balance_cents"), int)
    assert data.get("license_status") in (
        "PENDING_PAYMENT",
        "ACTIVE",
        "COMPLETED",
        "CANCELLED",
        "BREACHED",
    )
    assert data.get("payment_status") in (
        "UNPAID",
        "PARTIALLY_PAID",
        "PAID_IN_FULL",
        "REFUNDED",
    )
    assert isinstance(data.get("amendment_seq"), int)
    assert data["amendment_seq"] >= 0


def assert_performance(data: dict):
    _assert_common(data, "Performance")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert is_iso8601_timestamp(data.get("performance_at", ""))
    assert isinstance(data.get("reported_attendance"), int)
    assert isinstance(data.get("reported_gross_cents"), int)
    assert isinstance(data.get("gross_reported"), bool)
    assert isinstance(data.get("royalty_cents"), int)
    assert data.get("status") in ("SCHEDULED", "HELD", "CANCELLED")


def assert_rental(data: dict):
    _assert_common(data, "MaterialRental")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data.get("scripts_qty"), int)
    assert isinstance(data.get("scores_qty"), int)
    assert isinstance(data.get("deposit_cents"), int)
    assert data.get("deposit_status") in (
        "HELD",
        "RETURNED",
        "FORFEITED",
        "PARTIALLY_FORFEITED",
    )
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert isinstance(data.get("accrued_late_fee_cents"), int)
    assert data.get("status") in (
        "RESERVED",
        "SHIPPED",
        "RECEIVED",
        "RETURN_IN_TRANSIT",
        "RETURNED",
        "OVERDUE",
        "LOST",
    )


def assert_alteration_request(data: dict):
    _assert_common(data, "AlterationRequest")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert data.get("alteration_kind") in (
        "CUT",
        "GENDER_SWAP",
        "TEXT_CHANGE",
        "STAGING_CHANGE",
        "TRANSLATION",
    )
    assert isinstance(data.get("description"), str)
    assert data.get("status") in ("SUBMITTED", "APPROVED", "DENIED")


def assert_recording_grant(data: dict):
    _assert_common(data, "RecordingGrant")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert data.get("grant_kind") in (
        "CAST_RECORDING_AUDIO",
        "STREAMING_VIDEO",
        "ARCHIVAL_VIDEO",
    )
    assert data.get("distribution_scope") in (
        "CAST_CREW_ONLY",
        "PAYWALL",
        "PUBLIC_FREE",
    )
    assert data.get("status") in (
        "REQUESTED",
        "APPROVED",
        "DENIED",
        "EXERCISED",
        "REVOKED",
    )


def assert_royalty_payment(data: dict):
    """RoyaltyPayment is append-only: id + created_at only (no updated_at/version)."""
    _assert_common(data, "RoyaltyPayment", with_version=False)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 1
    assert is_iso8601_timestamp(data.get("paid_at", ""))


def assert_fine(data: dict):
    _assert_common(data, "Fine")
    assert is_valid_uuid(data.get("organization_id", ""))
    assert data.get("fine_kind") in (
        "OVERDUE_MATERIAL",
        "UNAUTHORIZED_ALTERATION",
        "UNAUTHORIZED_RECORDING",
        "LOSS",
    )
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 0
    assert data.get("status") in ("ASSESSED", "PAID", "WAIVED", "WRITTEN_OFF")


def assert_availability_snapshot(data: dict):
    """AvailabilitySnapshot is point-in-time: id + created_at only."""
    _assert_common(data, "AvailabilitySnapshot", with_version=False)
    assert is_valid_uuid(data.get("title_id", ""))
    assert isinstance(data.get("territory_code"), str)
    assert data.get("classification") in ("AMATEUR", "PROFESSIONAL")
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data.get("available"), bool)
    assert isinstance(data.get("blocking_restriction_ids"), list)
    assert isinstance(data.get("blocking_agreement_ids"), list)
    assert is_iso8601_timestamp(data.get("computed_at", ""))


def assert_deposit_conserved(rental: dict, deduction_cents: int = 0):
    """Deposit conservation: refund + deductions == deposit_cents (PRD §3.6)."""
    deposit = rental["deposit_cents"]
    status = rental["deposit_status"]
    if deduction_cents == 0:
        assert (
            status == "RETURNED"
        ), f"zero deductions must return the deposit, got {status}"
    elif deduction_cents < deposit:
        assert (
            status == "PARTIALLY_FORFEITED"
        ), f"partial deduction must partially forfeit, got {status}"
    else:
        assert (
            status == "FORFEITED"
        ), f"deduction >= deposit must forfeit fully, got {status}"
