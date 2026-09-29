"""Payload factories — one per resource, input fields only."""

import itertools

_counter = itertools.count(1)


def unique_suffix() -> int:
    """Monotonic counter for building unique emails and checksums."""
    return next(_counter)


# The canonical call configuration every scenario starts from. Overriding a
# single key keeps the rest of the calendar and fee schedule stable so expected
# money figures stay comparable across tests.
def create_exhibition_payload(**overrides) -> dict:
    defaults = {
        "title": "Regional Juried Biennial",
        "season_year": 2026,
        "call_opens_at": "2026-09-01T00:00:00Z",
        "call_closes_at": "2026-10-01T00:00:00Z",
        "notification_at": "2026-10-20T00:00:00Z",
        "delivery_window_start_at": "2026-11-02T00:00:00Z",
        "delivery_window_end_at": "2026-11-06T23:59:59Z",
        "opening_at": "2026-11-12T18:00:00Z",
        "closing_at": "2026-12-13T00:00:00Z",
        "entry_fee_base_cents": 4500,
        "entry_fee_additional_cents": 1500,
        "max_dimension_cm": 200,
        "max_weight_kg": 40,
        "per_work_insurance_cap_cents": 5000000,
        "allowed_media_categories": ["PAINTING", "PHOTOGRAPHY", "SCULPTURE"],
        "eligible_state_codes": ["CA", "OR"],
        "acceptance_capacity": 3,
        "waitlist_capacity": 1,
        "jury_quorum": 1,
        "advance_score_threshold": 7.0,
        "score_weight_technique": 0.4,
        "score_weight_originality": 0.35,
        "score_weight_relevance": 0.25,
        "commission_pct": 0.35,
        "sales_tax_pct": 0.0875,
        "award_budget_cents": 500000,
        "claim_deadline_days": 30,
        "works_included_in_base": 2,
        "member_discount_pct": 0.175,
        "max_works_per_entry": 5,
        "max_entries_per_artist": 1,
    }
    defaults.update(overrides)
    return defaults


def create_artist_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Ana Ruiz",
        "email": "ana.ruiz@example.org",
        "residency_state_code": "CA",
        "member_status": "MEMBER",
        "tax_form_on_file": True,
        "payout_method": "ACH",
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(exhibition_id: str, artist_id: str, **overrides) -> dict:
    defaults = {"exhibition_id": exhibition_id, "artist_id": artist_id}
    defaults.update(overrides)
    return defaults


def create_artwork_payload(**overrides) -> dict:
    defaults = {
        "title": "Ridge Line",
        "medium_category": "PAINTING",
        "width_cm": 90.0,
        "height_cm": 60.0,
        "depth_cm": 4.0,
        "weight_kg": 6.0,
        "year_created": 2025,
        "declared_value_cents": 400000,
        "for_sale": True,
        "list_price_cents": 250000,
    }
    defaults.update(overrides)
    return defaults


def create_artwork_image_payload(**overrides) -> dict:
    """A payload that satisfies all five digital-standard criteria and both
    metadata criteria."""
    defaults = {
        "role": "PRIMARY",
        "format": "JPEG",
        "pixel_long_edge": 2400,
        "pixel_short_edge": 1600,
        "file_bytes": 3145728,
        "color_profile": "SRGB",
        "capture_date": "2026-08-15T00:00:00Z",
        "credit_line": "Photo: Ana Ruiz",
        "checksum_sha256": f"{unique_suffix():064d}",
    }
    defaults.update(overrides)
    return defaults


def create_juror_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Iris Vega",
        "email": "iris@example.org",
        "expertise_categories": ["PAINTING"],
        "honorarium_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_jury_round_payload(exhibition_id: str, **overrides) -> dict:
    defaults = {
        "exhibition_id": exhibition_id,
        "round_number": 1,
        "round_type": "BLIND_SCORING",
        "opens_at": "2026-10-05T00:00:00Z",
        "closes_at": "2026-10-12T00:00:00Z",
        "quorum_required": 1,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(juror_id: str, expected_jury_round_version: int,
                              **overrides) -> dict:
    defaults = {
        "juror_id": juror_id,
        "session_start_at": "2026-10-06T09:00:00Z",
        "session_end_at": "2026-10-06T13:00:00Z",
        "expected_jury_round_version": expected_jury_round_version,
    }
    defaults.update(overrides)
    return defaults


def create_score_payload(artwork_id: str, technique: int = 7,
                         originality: int = 8, relevance: int = 9,
                         **overrides) -> dict:
    defaults = {
        "artwork_id": artwork_id,
        "technique": technique,
        "originality": originality,
        "relevance": relevance,
    }
    defaults.update(overrides)
    return defaults


def create_conflict_declaration_payload(artist_id: str,
                                        relation_type: str = "TEACHER_STUDENT",
                                        **overrides) -> dict:
    defaults = {"artist_id": artist_id, "relation_type": relation_type}
    defaults.update(overrides)
    return defaults


def create_wall_segment_payload(exhibition_id: str, **overrides) -> dict:
    defaults = {
        "exhibition_id": exhibition_id,
        "label": "W1",
        "length_cm": 600.0,
        "max_weight_kg": 60.0,
        "lighting_class": "MUSEUM",
    }
    defaults.update(overrides)
    return defaults


def create_condition_report_payload(stage: str = "INTAKE",
                                    condition_grade: str = "A",
                                    photo_count: int = 3, **overrides) -> dict:
    defaults = {
        "stage": stage,
        "condition_grade": condition_grade,
        "photo_count": photo_count,
    }
    defaults.update(overrides)
    return defaults


def create_installation_plan_payload(wall_segment_id: str, span_start_cm: float,
                                     span_end_cm: float,
                                     expected_wall_segment_version: int,
                                     **overrides) -> dict:
    defaults = {
        "wall_segment_id": wall_segment_id,
        "span_start_cm": span_start_cm,
        "span_end_cm": span_end_cm,
        "expected_wall_segment_version": expected_wall_segment_version,
    }
    defaults.update(overrides)
    return defaults


def create_sponsor_payload(exhibition_id: str, **overrides) -> dict:
    defaults = {
        "exhibition_id": exhibition_id,
        "name": "Silver Floor LLC",
        "contribution_cents": 1000000,
        "purchase_award_budget_cents": 300000,
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(exhibition_id: str, artwork_id: str,
                         category: str = "BEST_IN_SHOW",
                         prize_cents: int = 100000, **overrides) -> dict:
    defaults = {
        "exhibition_id": exhibition_id,
        "artwork_id": artwork_id,
        "category": category,
        "prize_cents": prize_cents,
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(artwork_id: str, sale_price_cents: int = 250000,
                        **overrides) -> dict:
    defaults = {
        "artwork_id": artwork_id,
        "buyer_name": "Marta Nyberg",
        "buyer_region_code": "CA",
        "sale_price_cents": sale_price_cents,
    }
    defaults.update(overrides)
    return defaults
