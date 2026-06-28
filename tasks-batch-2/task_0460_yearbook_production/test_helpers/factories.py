"""Payload factories — one per entity, input fields only (Yearbook Production PRD §3)."""

DEFAULTS = {
    "SCHOOL_NAME": "Lincoln High",
    "ACADEMIC_YEAR": "2025-2026",
    "TARGET_PAGE_COUNT": 96,
    "UNIT_COST_CENTS": 1200,
    "PRESALE_OPEN_ISO": "2026-01-01T00:00:00Z",
    "PRESALE_CLOSE_ISO": "2026-03-01T00:00:00Z",
}


def create_yearbook_payload(**overrides) -> dict:
    defaults = {
        "school_name": DEFAULTS["SCHOOL_NAME"],
        "academic_year": DEFAULTS["ACADEMIC_YEAR"],
        "target_page_count": DEFAULTS["TARGET_PAGE_COUNT"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "presale_open_iso": DEFAULTS["PRESALE_OPEN_ISO"],
        "presale_close_iso": DEFAULTS["PRESALE_CLOSE_ISO"],
    }
    defaults.update(overrides)
    return defaults


def create_page_payload(yearbook_id: str, page_number: int, section: str,
                        template_code: str = "T", **overrides) -> dict:
    defaults = {
        "yearbook_id": yearbook_id,
        "page_number": page_number,
        "section": section,
        "template_code": template_code,
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(ladder_page_id: str, kind: str = "PHOTO",
                              contributor_id: str = "c-1",
                              asset_ref: str = "img/1.jpg", **overrides) -> dict:
    defaults = {
        "ladder_page_id": ladder_page_id,
        "kind": kind,
        "contributor_id": contributor_id,
        "asset_ref": asset_ref,
    }
    defaults.update(overrides)
    return defaults


def create_staff_assignment_payload(yearbook_id: str, staff_user_id: str = "staff-9",
                                    role_title: str = "EDITOR",
                                    deadline_iso: str = "2026-06-01T00:00:00Z",
                                    **overrides) -> dict:
    defaults = {
        "yearbook_id": yearbook_id,
        "staff_user_id": staff_user_id,
        "role_title": role_title,
        "deadline_iso": deadline_iso,
    }
    defaults.update(overrides)
    return defaults


def create_ad_contract_payload(yearbook_id: str, ladder_page_id: str,
                              sponsor_name: str = "Acme", size: str = "FULL",
                              **overrides) -> dict:
    defaults = {
        "yearbook_id": yearbook_id,
        "ladder_page_id": ladder_page_id,
        "sponsor_name": sponsor_name,
        "size": size,
    }
    defaults.update(overrides)
    return defaults


def create_proof_payload(yearbook_id: str, **overrides) -> dict:
    defaults = {"yearbook_id": yearbook_id}
    defaults.update(overrides)
    return defaults


def create_presale_order_payload(yearbook_id: str, buyer_name: str = "Pat",
                                quantity: int = 1, **overrides) -> dict:
    defaults = {
        "yearbook_id": yearbook_id,
        "buyer_name": buyer_name,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_print_run_payload(yearbook_id: str, quantity: int, expected_yearbook_version: int,
                            delivery_address: str = "1 School St", **overrides) -> dict:
    defaults = {
        "yearbook_id": yearbook_id,
        "quantity": quantity,
        "delivery_address": delivery_address,
        "expected_yearbook_version": expected_yearbook_version,
    }
    defaults.update(overrides)
    return defaults
