"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(each test runs against a freshly restarted server with an empty database).
Uses get_success_data() internally so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_asset_class_payload,
    create_capital_project_payload,
    create_cip_cost_line_payload,
    create_count_line_payload,
    create_disposal_payload,
    create_external_schedule_payload,
    create_fixed_asset_payload,
    create_impairment_review_payload,
    create_inventory_run_payload,
)
from .test_users import TEST_USERS

ACCT = TEST_USERS["asset_accountant_headers"]
CTRL = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
TAX = TEST_USERS["tax_analyst_headers"]


# --- Tier 1: policy + asset state progression ---

def create_class(**overrides) -> dict:
    """Create an asset class (Controller). Returns the created class."""
    return get_success_data(
        api_client.create_asset_class(create_asset_class_payload(**overrides), CTRL)
    )


def create_asset(asset_class_id: str, **overrides) -> dict:
    """Register a purchased/component asset (AssetAccountant). Born DRAFT."""
    return get_success_data(
        api_client.create_fixed_asset(
            create_fixed_asset_payload(asset_class_id, **overrides), ACCT
        )
    )


def create_in_service_asset(asset_class_id: str,
                            in_service_date: str = "2026-01-10",
                            **overrides) -> dict:
    """Register an asset and place it in service. Returns the updated asset."""
    asset = create_asset(asset_class_id, **overrides)
    return get_success_data(
        api_client.place_in_service(
            asset["id"], {"in_service_date": in_service_date}, ACCT
        )
    )


def refresh_asset(asset_id: str) -> dict:
    return get_success_data(api_client.get_fixed_asset(asset_id, ACCT))


def current_asset_version(asset_id: str) -> int:
    return refresh_asset(asset_id)["version"]


# --- Tier 4: depreciation run checkpoint / accumulation targeting ---

def create_and_post_run(period: str) -> dict:
    """Create a depreciation run for `period` and post it. Returns POSTED run."""
    run = get_success_data(
        api_client.create_depreciation_run({"period": period}, ACCT)
    )
    return get_success_data(api_client.post_depreciation_run(run["id"], ACCT))


def setup_asset_with_posted_runs(periods: List[str],
                                 asset_class_id: Optional[str] = None,
                                 in_service_date: str = "2026-01-10",
                                 **asset_overrides) -> Tuple[dict, List[dict]]:
    """In-service asset plus one posted run per period, in order.

    Returns (asset, [posted runs]). The asset is refreshed after the runs.
    """
    if asset_class_id is None:
        asset_class_id = create_class()["id"]
    asset = create_in_service_asset(
        asset_class_id, in_service_date=in_service_date, **asset_overrides
    )
    runs = [create_and_post_run(period) for period in periods]
    return refresh_asset(asset["id"]), runs


def book_entries(asset_id: str) -> List[dict]:
    data, _meta = validate_paginated(
        api_client.list_depreciation_entries(
            ACCT, params={"asset_id": asset_id, "ledger": "BOOK"}
        )
    )
    return data


def tax_entries(asset_id: str) -> List[dict]:
    data, _meta = validate_paginated(
        api_client.list_depreciation_entries(
            ACCT, params={"asset_id": asset_id, "ledger": "TAX"}
        )
    )
    return data


def entries_for_disposal(disposal_id: str) -> List[dict]:
    data, _meta = validate_paginated(
        api_client.list_depreciation_entries(
            ACCT, params={"disposal_id": disposal_id}
        )
    )
    return data


# --- Tier 2: CIP project hierarchy ---

def create_project(asset_class_id: str, **overrides) -> dict:
    """Create an OPEN capital project (AssetAccountant)."""
    return get_success_data(
        api_client.create_capital_project(
            create_capital_project_payload(asset_class_id, **overrides), ACCT
        )
    )


def post_cost_line(project_id: str, amount_cents: int, **overrides) -> dict:
    """Post a single cost line to an OPEN project. Returns the line."""
    return get_success_data(
        api_client.create_cip_cost_line(
            create_cip_cost_line_payload(
                project_id, amount_cents=amount_cents, **overrides
            ),
            ACCT,
        )
    )


def create_project_with_lines(asset_class_id: str, amounts: List[int],
                              **project_overrides) -> Tuple[dict, List[dict]]:
    """OPEN project plus one POSTED cost line per amount. Returns (project, lines)."""
    project = create_project(asset_class_id, **project_overrides)
    lines = [post_cost_line(project["id"], amount) for amount in amounts]
    project = get_success_data(api_client.get_capital_project(project["id"], ACCT))
    return project, lines


def capitalize_project(project_id: str, asset_tag: str,
                       description: str = "Capitalized asset") -> dict:
    """Capitalize an OPEN project (Controller, distinct from the creator)."""
    return get_success_data(
        api_client.capitalize_project(
            project_id, {"asset_tag": asset_tag, "description": description}, CTRL
        )
    )


# --- Tier 3: disposal lifecycle shortcuts ---

def create_disposal_request(asset_id: str, **overrides) -> dict:
    """Request a disposal (AssetAccountant). Born REQUESTED."""
    return get_success_data(
        api_client.create_disposal(create_disposal_payload(asset_id, **overrides),
                                   ACCT)
    )


def create_approved_disposal(asset_id: str, **overrides) -> dict:
    """Request + approve a disposal. Returns the APPROVED disposal."""
    disposal = create_disposal_request(asset_id, **overrides)
    return get_success_data(api_client.approve_disposal(disposal["id"], CTRL))


def post_approved_disposal(disposal_id: str) -> dict:
    """Post an APPROVED disposal (AssetAccountant). Returns the POSTED disposal."""
    return get_success_data(api_client.post_disposal(disposal_id, ACCT))


def create_and_post_disposal(asset_id: str, **overrides) -> dict:
    """Full disposal lifecycle: request, approve, post. Returns POSTED disposal."""
    disposal = create_approved_disposal(asset_id, **overrides)
    return post_approved_disposal(disposal["id"])


# --- Tier 3: impairment review shortcuts ---

def create_open_review(asset_id: str, indicator: str = "DAMAGE") -> dict:
    """Open a MANUAL impairment review (AssetAccountant). Born OPEN."""
    return get_success_data(
        api_client.create_impairment_review(
            create_impairment_review_payload(asset_id, indicator=indicator), ACCT
        )
    )


# --- Tier 2: inventory run helpers ---

def create_inventory_run(**overrides) -> dict:
    """Create an inventory run (InventoryClerk). Born COUNTING; lines seeded."""
    return get_success_data(
        api_client.create_inventory_run(create_inventory_run_payload(**overrides),
                                        CLERK)
    )


def count_asset(run_id: str, asset_id: str, **overrides) -> dict:
    """Record (upsert) a physical count for a seeded line (InventoryClerk)."""
    return get_success_data(
        api_client.upsert_count_line(
            run_id, create_count_line_payload(asset_id, **overrides), CLERK
        )
    )


# --- Tier 3: external schedule helpers ---

def create_schedule(asset_id: str, **overrides) -> dict:
    """Import an external schedule row (TaxAnalyst). Born IMPORTED."""
    return get_success_data(
        api_client.create_external_schedule(
            create_external_schedule_payload(asset_id, **overrides), TAX
        )
    )
