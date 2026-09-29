"""Entity assertions and domain invariant checkers."""

import datetime as _dt

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ArtworkStatus,
    AssignmentStatus,
    AwardStatus,
    EntryStatus,
    ExhibitionStatus,
    JuryRoundStatus,
    JurorStatus,
    PlacementStatus,
    SaleStatus,
    SettlementStatus,
)

_VERSIONED_KEYS = ("id", "created_at", "updated_at", "version")
_APPEND_ONLY_KEYS = ("id", "created_at")


def _instant(value):
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    moment = _dt.datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    return moment.astimezone(_dt.timezone.utc)


def assert_same_instant(actual, expected, message: str = "") -> None:
    """Two ISO 8601 UTC strings denote the same instant.

    The PRD pins a three-fractional-digit rendering only for `created_at`,
    `updated_at` and `api_request_timestamp`, and says client-supplied
    timestamps are stored as given. It says nothing about how a server-derived
    or clock-stamped instant is rendered, so these comparisons are made on the
    instant rather than on its lexical form.
    """
    assert _instant(actual) == _instant(expected), (
        message or f"{actual!r} and {expected!r} must denote the same instant"
    )


def _assert_versioned_envelope(data: dict, label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def _assert_append_only_envelope(data: dict, label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, (
        f"{label} is append-only: updated_at must be absent from the resource"
    )
    assert "version" not in data, (
        f"{label} is append-only: version must be absent from the resource"
    )


# ─── Versioned resources ──────────────────────────────

def assert_exhibition(data: dict) -> None:
    _assert_versioned_envelope(data, "Exhibition")
    assert data["status"] in [s.value for s in ExhibitionStatus]
    assert data["settlement_status"] in [s.value for s in SettlementStatus]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["season_year"], int)
    for money in (
        "insured_value_total_cents", "insurance_premium_cents",
        "award_committed_cents", "jury_cost_committed_cents",
        "sales_gross_cents", "commission_total_cents", "sales_tax_total_cents",
        "artist_payable_total_cents", "payouts_released_cents",
        "council_retention_cents",
    ):
        assert isinstance(data[money], int), f"Exhibition.{money} must be integer cents"
    for count in ("shortlisted_count", "accepted_count", "waitlisted_count"):
        assert isinstance(data[count], int) and data[count] >= 0


def assert_artist(data: dict) -> None:
    _assert_versioned_envelope(data, "Artist")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["member_status"] in ("MEMBER", "NON_MEMBER")
    assert data["payout_method"] in ("CHECK", "ACH")
    assert isinstance(data["tax_form_on_file"], bool)
    assert isinstance(data["payout_hold"], bool)
    assert isinstance(data["unclaimed_forfeit_count"], int)


def assert_entry(data: dict) -> None:
    _assert_versioned_envelope(data, "Entry")
    assert data["status"] in [s.value for s in EntryStatus]
    assert is_valid_uuid(data["exhibition_id"])
    assert is_valid_uuid(data["artist_id"])
    assert isinstance(data["works_count"], int) and data["works_count"] >= 0
    assert isinstance(data["fee_paid_cents"], int)
    assert isinstance(data["fee_waived"], bool)
    assert isinstance(data["shortlisted_count"], int)


def assert_artwork(data: dict) -> None:
    _assert_versioned_envelope(data, "Artwork")
    assert data["status"] in [s.value for s in ArtworkStatus]
    assert data["placement_status"] in [s.value for s in PlacementStatus]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["declared_value_cents"], int)
    assert isinstance(data["for_sale"], bool)
    assert isinstance(data["storage_fee_cents"], int)
    assert isinstance(data["primary_image_count"], int)
    assert isinstance(data["blind_label"], str) and data["blind_label"]
    expected_longest = max(data["width_cm"], data["height_cm"], data["depth_cm"])
    assert data["longest_edge_cm"] == expected_longest, (
        f"longest_edge_cm must be the greatest of the three dimensions: "
        f"expected {expected_longest}, got {data['longest_edge_cm']}"
    )


def assert_juror(data: dict) -> None:
    _assert_versioned_envelope(data, "Juror")
    assert data["status"] in [s.value for s in JurorStatus]
    assert isinstance(data["expertise_categories"], list) and data["expertise_categories"]
    assert isinstance(data["honorarium_cents"], int)
    assert isinstance(data["honorarium_committed_cents"], int)
    assert isinstance(data["honorarium_paid_cents"], int)
    assert isinstance(data["conflict_count"], int)
    assert isinstance(data["assignment_count"], int)


def assert_jury_round(data: dict) -> None:
    _assert_versioned_envelope(data, "JuryRound")
    assert data["status"] in [s.value for s in JuryRoundStatus]
    assert data["round_type"] in ("BLIND_SCORING", "DELIBERATION")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["quorum_required"], int)
    assert isinstance(data["reopen_count"], int)
    assert isinstance(data["scored_artwork_count"], int)
    assert isinstance(data["quorum_shortfall_count"], int)


def assert_juror_assignment(data: dict) -> None:
    _assert_versioned_envelope(data, "JurorAssignment")
    assert data["status"] in [s.value for s in AssignmentStatus]
    assert isinstance(data["session_minutes"], int)
    assert isinstance(data["honorarium_share_cents"], int)
    assert isinstance(data["scores_submitted_count"], int)


def assert_wall_segment(data: dict) -> None:
    _assert_versioned_envelope(data, "WallSegment")
    assert data["lighting_class"] in ("STANDARD", "MUSEUM")
    assert_wall_space_conserved(data)


def assert_sponsor(data: dict) -> None:
    _assert_versioned_envelope(data, "Sponsor")
    assert data["recognition_tier"] in (
        "NONE", "BRONZE", "SILVER", "GOLD", "PRESENTING"
    )
    assert isinstance(data["contribution_cents"], int)
    assert isinstance(data["purchase_award_committed_cents"], int)


def assert_award(data: dict) -> None:
    _assert_versioned_envelope(data, "Award")
    assert data["status"] in [s.value for s in AwardStatus]
    assert data["category"] in (
        "BEST_IN_SHOW", "JURORS_CHOICE", "MEDIUM_MERIT", "PURCHASE_AWARD"
    )
    assert isinstance(data["prize_cents"], int)
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]


def assert_sale(data: dict) -> None:
    _assert_versioned_envelope(data, "Sale")
    assert data["status"] in [s.value for s in SaleStatus]
    assert data["sale_type"] in ("GALLERY_SALE", "PURCHASE_AWARD")
    for money in (
        "sale_price_cents", "taxable_base_cents", "sales_tax_cents",
        "commission_cents", "artist_payable_cents", "buyer_total_cents",
    ):
        assert isinstance(data[money], int), f"Sale.{money} must be integer cents"
    assert_sale_split_consistent(data)


# ─── Append-only evidence records ─────────────────────

def assert_artwork_image(data: dict) -> None:
    _assert_append_only_envelope(data, "ArtworkImage")
    assert data["role"] in ("PRIMARY", "DETAIL")
    assert data["format"] in ("JPEG", "PNG", "TIFF")
    assert data["color_profile"] in ("SRGB", "ADOBE_RGB", "CMYK")
    assert isinstance(data["pixel_long_edge"], int)
    assert isinstance(data["pixel_short_edge"], int)
    assert isinstance(data["file_bytes"], int)


def assert_conflict_declaration(data: dict) -> None:
    _assert_append_only_envelope(data, "ConflictDeclaration")
    assert data["relation_type"] in (
        "FAMILY", "TEACHER_STUDENT", "SAME_GALLERY", "COLLABORATOR",
        "FINANCIAL_INTEREST",
    )
    assert isinstance(data["voided_score_count"], int)


def assert_score(data: dict) -> None:
    _assert_append_only_envelope(data, "Score")
    for criterion in ("technique", "originality", "relevance"):
        assert isinstance(data[criterion], int)
        assert 1 <= data[criterion] <= 10, f"Score.{criterion} must be 1..10 inclusive"
    assert isinstance(data["expertise_match"], bool)
    assert isinstance(data["voided_by_conflict"], bool)
    assert isinstance(data["composite_score"], (int, float))
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_condition_report(data: dict) -> None:
    _assert_append_only_envelope(data, "ConditionReport")
    assert data["stage"] in ("INTAKE", "DEINSTALL")
    assert data["condition_grade"] in ("A", "B", "C", "DAMAGED")
    assert isinstance(data["photo_count"], int) and data["photo_count"] >= 1
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]


# ─── Domain invariants ────────────────────────────────

def assert_wall_space_conserved(wall: dict) -> None:
    """`occupied_cm` plus `available_cm` still equals `length_cm`."""
    total = wall["occupied_cm"] + wall["available_cm"]
    assert total == wall["length_cm"], (
        f"occupied_cm + available_cm must equal length_cm: "
        f"{wall['occupied_cm']} + {wall['available_cm']} != {wall['length_cm']}"
    )


def assert_sale_split_consistent(sale: dict) -> None:
    """The split's internal identities: payable is base minus commission and the
    buyer total is base plus tax."""
    assert sale["artist_payable_cents"] == (
        sale["taxable_base_cents"] - sale["commission_cents"]
    ), "artist_payable_cents must be taxable_base_cents minus commission_cents"
    assert sale["buyer_total_cents"] == (
        sale["taxable_base_cents"] + sale["sales_tax_cents"]
    ), "buyer_total_cents must be taxable_base_cents plus sales_tax_cents"


def assert_two_decimal_score(value) -> None:
    assert value is not None, "score must not be null"
    assert round(float(value), 2) == float(value), (
        f"score {value} must carry at most two decimal places"
    )


def assert_zeroed_ledger(exhibition: dict) -> None:
    """Every computed count and money aggregate sits at zero."""
    for field in (
        "shortlisted_count", "accepted_count", "waitlisted_count",
        "insured_value_total_cents", "insurance_premium_cents",
        "award_committed_cents", "jury_cost_committed_cents",
        "sales_gross_cents", "commission_total_cents", "sales_tax_total_cents",
        "artist_payable_total_cents", "payouts_released_cents",
        "council_retention_cents",
    ):
        assert exhibition[field] == 0, (
            f"Exhibition.{field} must start at 0, got {exhibition[field]}"
        )
