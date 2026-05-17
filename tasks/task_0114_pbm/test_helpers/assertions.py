"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract. They are intentionally permissive on optional fields —
when PRD prose is silent on a specific projection (e.g., whether a
nullable field is present-with-null vs absent), the assertion does not
pin it.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """PRD §2.4: "id — a server-minted UUID with no type prefix; the
    canonical identifier used in path parameters and foreign-key
    references." and "created_at — an ISO 8601 UTC timestamp with
    three fractional digits, recording the moment the resource was
    first persisted." """
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: "updated_at — an ISO 8601 UTC timestamp with three
    fractional digits, refreshed on every mutation …" and "version — a
    non-negative integer that begins at the value chosen by the server
    on creation and increments by one on every mutation that changes
    any other field of the resource." """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 0, (
        f"version must be a non-negative integer, "
        f"got {data.get('version')!r}"
    )


def _assert_no_updated_at_or_version(data: Dict[str, Any]) -> None:
    """PRD §2.4 (LedgerEntry exception): "it has no updated_at and no
    version, because once a rebate accrual or clawback is posted it is
    never altered." """
    assert "updated_at" not in data, (
        "append-only resource must not carry updated_at"
    )
    assert "version" not in data, (
        "append-only resource must not carry version"
    )


def assert_version_incremented_by_one(new_version: int,
                                      old_version: int) -> None:
    """PRD §2.4: "version … increments by one on every mutation that
    changes any other field of the resource." """
    assert new_version == old_version + 1, (
        f"version must increment by exactly 1, "
        f"got {old_version} -> {new_version}"
    )


# ---------------------------------------------------------------------------
# Plan — PRD §3.1
# ---------------------------------------------------------------------------
PLAN_STATUSES = {"ACTIVE", "ARCHIVED"}


def assert_plan(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("name"), str) and data["name"]
    # PRD §3.1: "deductible_cents … non-negative".
    assert isinstance(data.get("deductible_cents"), int)
    assert data["deductible_cents"] >= 0
    # PRD §3.1: "the out-of-pocket maximum must be at least as large
    # as the deductible".
    assert isinstance(data.get("oop_max_cents"), int)
    assert data["oop_max_cents"] >= 0
    assert data["oop_max_cents"] >= data["deductible_cents"]
    # PRD §3.1: "coinsurance_rate between 0 and 1 inclusive".
    assert isinstance(data.get("coinsurance_rate"), (int, float))
    assert 0.0 <= float(data["coinsurance_rate"]) <= 1.0
    # PRD §3.1: "mail_order_discount_rate strictly above 0 and at
    # most 1".
    assert isinstance(data.get("mail_order_discount_rate"), (int, float))
    rate = float(data["mail_order_discount_rate"])
    assert 0.0 < rate <= 1.0
    # PRD §3.1: status ACTIVE | ARCHIVED.
    assert data.get("status") in PLAN_STATUSES


# ---------------------------------------------------------------------------
# Drug — PRD §3.1
# ---------------------------------------------------------------------------
DRUG_STATUSES = {"ACTIVE", "ARCHIVED"}


def assert_drug(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    # PRD §3.1: ndc "must consist of exactly eleven digit characters".
    assert isinstance(data.get("ndc"), str)
    assert len(data["ndc"]) == 11 and data["ndc"].isdigit()
    assert isinstance(data.get("generic_name"), str) and data["generic_name"]
    assert isinstance(data.get("brand_name"), str) and data["brand_name"]
    # PRD §3.1: unit_allowed_cents non-negative.
    assert isinstance(data.get("unit_allowed_cents"), int)
    assert data["unit_allowed_cents"] >= 0
    # PRD §3.1: is_specialty + requires_prior_auth booleans with
    # defaults of false.
    assert isinstance(data.get("is_specialty"), bool)
    assert isinstance(data.get("requires_prior_auth"), bool)
    # PRD §3.1: status ACTIVE | ARCHIVED.
    assert data.get("status") in DRUG_STATUSES


# ---------------------------------------------------------------------------
# FormularyEntry — PRD §3.1
# ---------------------------------------------------------------------------
FORMULARY_STATUSES = {"ACTIVE", "ARCHIVED"}


def assert_formulary_entry(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("plan_id", ""))
    assert is_valid_uuid(data.get("drug_id", ""))
    # PRD §3.1: "Tiers are integers from 1 (preferred generic) to 5".
    assert isinstance(data.get("tier"), int)
    assert 1 <= data["tier"] <= 5
    # PRD §3.1 / §1.1: copay_cents non-negative integer.
    assert isinstance(data.get("copay_cents"), int)
    assert data["copay_cents"] >= 0
    assert data.get("status") in FORMULARY_STATUSES


# ---------------------------------------------------------------------------
# Member — PRD §3.2
# ---------------------------------------------------------------------------
MEMBER_STATUSES = {"ACTIVE", "SUSPENDED", "TERMINATED"}


def assert_member(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str) and data["date_of_birth"]
    # PRD §3.2: "enrollment_status begins at ACTIVE (the other legal
    # values are SUSPENDED and TERMINATED)".
    assert data.get("enrollment_status") in MEMBER_STATUSES
    # PRD §3.2: "ytd_deductible_paid_cents and ytd_oop_paid_cents
    # both begin at zero" and remain integer cents.
    assert isinstance(data.get("ytd_deductible_paid_cents"), int)
    assert data["ytd_deductible_paid_cents"] >= 0
    assert isinstance(data.get("ytd_oop_paid_cents"), int)
    assert data["ytd_oop_paid_cents"] >= 0
    # PRD §3.2: benefit_year_start ISO 8601.
    assert is_iso8601_timestamp(data.get("benefit_year_start", ""))


# ---------------------------------------------------------------------------
# PriorAuthorization — PRD §3.3
# ---------------------------------------------------------------------------
PA_STATUSES = {
    "DRAFT", "SUBMITTED", "INFO_REQUESTED",
    "APPROVED", "DENIED", "REVOKED", "EXPIRED",
}


def assert_prior_authorization(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("drug_id", ""))
    # PRD §3.3: prescriber_npi "exactly ten digit characters".
    npi = data.get("prescriber_npi", "")
    assert isinstance(npi, str) and len(npi) == 10 and npi.isdigit()
    assert isinstance(data.get("clinical_rationale"), str)
    assert len(data["clinical_rationale"]) > 0
    assert data.get("status") in PA_STATUSES
    # PRD §3.3: revision_count int >= 0.
    assert isinstance(data.get("revision_count"), int)
    assert data["revision_count"] >= 0


# ---------------------------------------------------------------------------
# Claim — PRD §3.4-§3.7
# ---------------------------------------------------------------------------
CLAIM_STATUSES = {"SUBMITTED", "ADJUDICATED", "PAID", "REVERSED", "REJECTED"}
CLAIM_PAYMENT_STATUSES = {"UNPAID", "PAID", "REFUNDED"}
CLAIM_CHANNELS = {"RETAIL_30", "MAIL_ORDER_90", "SPECIALTY"}


def assert_claim(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("drug_id", ""))
    assert data.get("channel") in CLAIM_CHANNELS
    # PRD §3.4: quantity at least 1, days_supply positive.
    assert isinstance(data.get("days_supply"), int)
    assert data["days_supply"] >= 1
    assert isinstance(data.get("quantity"), int)
    assert data["quantity"] >= 1
    # PRD §3.4 / §3.7: integer-cent monetary fields are non-negative
    # integers (allowed/plan_paid/card_paid/member_cost). estimated
    # is computed on creation; the others are computed on adjudicate
    # and may still be 0 in SUBMITTED state.
    for field in (
        "estimated_member_cost_cents",
        "adjudicated_allowed_cents",
        "adjudicated_member_cost_cents",
        "adjudicated_plan_paid_cents",
        "copay_card_paid_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be integer cents"
        )
        assert data[field] >= 0
    assert data.get("status") in CLAIM_STATUSES
    assert data.get("payment_status") in CLAIM_PAYMENT_STATUSES


# ---------------------------------------------------------------------------
# CopayCard — PRD §3.8
# ---------------------------------------------------------------------------
COPAY_CARD_STATUSES = {"ACTIVE", "EXHAUSTED", "TERMINATED"}


def assert_copay_card(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("drug_id", ""))
    # PRD §3.8: both caps are non-negative integers, per-claim <= max.
    assert isinstance(data.get("max_benefit_cents"), int)
    assert data["max_benefit_cents"] >= 0
    assert isinstance(data.get("per_claim_cap_cents"), int)
    assert 0 <= data["per_claim_cap_cents"] <= data["max_benefit_cents"]
    # PRD §3.8: "used_cents … begins at zero".
    assert isinstance(data.get("used_cents"), int)
    assert data["used_cents"] >= 0
    assert data["used_cents"] <= data["max_benefit_cents"]
    assert data.get("status") in COPAY_CARD_STATUSES


# ---------------------------------------------------------------------------
# RebateAgreement — PRD §3.6
# ---------------------------------------------------------------------------
REBATE_AGREEMENT_STATUSES = {"ACTIVE", "TERMINATED"}


def assert_rebate_agreement(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("drug_id", ""))
    assert isinstance(data.get("manufacturer_name"), str)
    assert data["manufacturer_name"]
    # PRD §3.6: "rebate_rate between 0 and 1 inclusive".
    assert isinstance(data.get("rebate_rate"), (int, float))
    assert 0.0 <= float(data["rebate_rate"]) <= 1.0
    # PRD §3.6: "clawback_window_days non-negative integer".
    assert isinstance(data.get("clawback_window_days"), int)
    assert data["clawback_window_days"] >= 0
    assert data.get("status") in REBATE_AGREEMENT_STATUSES


# ---------------------------------------------------------------------------
# LedgerEntry — PRD §3.9
# ---------------------------------------------------------------------------
LEDGER_ENTRY_TYPES = {"REBATE_ACCRUED", "REBATE_CLAWBACK"}


def assert_ledger_entry(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: LedgerEntry "has no updated_at and no version".
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert is_valid_uuid(data.get("rebate_agreement_id", ""))
    assert data.get("entry_type") in LEDGER_ENTRY_TYPES
    assert isinstance(data.get("amount_cents"), int)
    # PRD §3.9: "REBATE_ACCRUED (a positive amount_cents, money
    # flowing toward the PBM) and REBATE_CLAWBACK (a negative
    # amount_cents, money flowing back to the manufacturer)."
    if data["entry_type"] == "REBATE_ACCRUED":
        assert data["amount_cents"] >= 0
    else:
        assert data["amount_cents"] <= 0
    # PRD §3.9: "a posted_at timestamp drawn from the simulated
    # clock."
    assert is_iso8601_timestamp(data.get("posted_at", ""))


# ---------------------------------------------------------------------------
# Cross-entity invariant checkers.
# ---------------------------------------------------------------------------
def assert_ledger_zero_sum_for_claim(entries: list) -> None:
    """PRD §3.7: "the invariant after this second posting is that the
    sum of every ledger entry's amount_cents for the same claim_id is
    exactly zero." """
    total = sum(int(e["amount_cents"]) for e in entries)
    assert total == 0, (
        f"ledger entries for the claim must sum to 0, got {total}"
    )


__all__ = [
    "PLAN_STATUSES",
    "DRUG_STATUSES",
    "FORMULARY_STATUSES",
    "MEMBER_STATUSES",
    "PA_STATUSES",
    "CLAIM_STATUSES",
    "CLAIM_PAYMENT_STATUSES",
    "CLAIM_CHANNELS",
    "COPAY_CARD_STATUSES",
    "REBATE_AGREEMENT_STATUSES",
    "LEDGER_ENTRY_TYPES",
    "assert_version_incremented_by_one",
    "assert_plan",
    "assert_drug",
    "assert_formulary_entry",
    "assert_member",
    "assert_prior_authorization",
    "assert_claim",
    "assert_copay_card",
    "assert_rebate_agreement",
    "assert_ledger_entry",
    "assert_ledger_zero_sum_for_claim",
]
