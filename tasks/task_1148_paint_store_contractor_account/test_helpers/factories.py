"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""
import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq):04d}"


def create_contractor_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": _uniq("Co"),
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_job_account_payload(contractor_account_id, jurisdiction_id, **overrides) -> dict:
    defaults = {
        "contractor_account_id": contractor_account_id,
        "jurisdiction_id": jurisdiction_id,
        "job_name": _uniq("Job"),
        "site_address": "1 Main St",
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("JUR"),
        "name": "Test Jurisdiction",
    }
    defaults.update(overrides)
    return defaults


def create_voc_rule_payload(jurisdiction_id, **overrides) -> dict:
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "category": "FLAT",
        "max_voc_gpl": 250,
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "name": "Test Product",
        "category": "FLAT",
        "voc_gpl": TEST_DEFAULTS["VOC_GPL"],
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
        "tintable": False,
    }
    defaults.update(overrides)
    return defaults


def create_tint_formula_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "color_code": _uniq("SW"),
        "name": "Test Formula",
        "shots": [{"colorant_code": "B1", "ounces_128ths": 8}],
    }
    defaults.update(overrides)
    return defaults


def create_color_match_request_payload(contractor_account_id, product_id, **overrides) -> dict:
    defaults = {
        "contractor_account_id": contractor_account_id,
        "product_id": product_id,
        "sample_reference": _uniq("S"),
    }
    defaults.update(overrides)
    return defaults


def create_match_proposal_payload(**overrides) -> dict:
    defaults = {
        "color_code": _uniq("SW"),
        "name": "Proposal",
        "shots": [{"colorant_code": "B1", "ounces_128ths": 8}],
    }
    defaults.update(overrides)
    return defaults


def create_product_bulletin_payload(product_id, replacement_product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "replacement_product_id": replacement_product_id,
        "title": "Discontinuation",
        "effective_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_spec_sheet_payload(lines, **overrides) -> dict:
    defaults = {
        "project_code": _uniq("PRJ"),
        "architect_name": "Test Architect",
        "title": "Test Spec",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_spec_line_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "specified_qty": 5,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(contractor_account_id, job_account_id,
                         expected_contractor_account_version, lines, **overrides) -> dict:
    defaults = {
        "contractor_account_id": contractor_account_id,
        "job_account_id": job_account_id,
        "expected_contractor_account_version": expected_contractor_account_version,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(**overrides) -> dict:
    defaults = {"quantity": 1}
    defaults.update(overrides)
    return defaults


def create_delivery_payload(order_id, job_account_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "job_account_id": job_account_id,
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_rebate_statement_payload(contractor_account_id, period_start, period_end,
                                    **overrides) -> dict:
    defaults = {
        "contractor_account_id": contractor_account_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_loyalty_redemption_payload(contractor_account_id, points_to_redeem,
                                      **overrides) -> dict:
    defaults = {
        "contractor_account_id": contractor_account_id,
        "points_to_redeem": points_to_redeem,
    }
    defaults.update(overrides)
    return defaults


def create_mistint_listing_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "quantity": 1,
        "cost_basis_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults
