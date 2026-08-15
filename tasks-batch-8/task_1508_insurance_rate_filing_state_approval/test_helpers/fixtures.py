"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server before each test, so nothing is
carried over. Setup calls use the lenient get_success_data() validator so a
broken precondition surfaces as a clear "Setup step failed" message.
"""
from typing import List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_component_payload,
    create_deviation_payload,
    create_filing_payload,
    create_indication_payload,
    create_objection_payload,
    create_policy_payload,
    create_product_payload,
    create_profile_payload,
    create_response_payload,
    create_wave_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
ACT1 = TEST_USERS["actuary_headers"]
ACT2 = TEST_USERS["actuary2_headers"]
ANALYST = TEST_USERS["analyst_headers"]
OFFICER = TEST_USERS["officer_headers"]
REGULATOR = TEST_USERS["regulator_headers"]
LEAD = TEST_USERS["lead_headers"]


# ─── Primitive steps ────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4); triggers the system sweep."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_product(product_code: str = "PPA", name: str = "Personal Auto") -> dict:
    return get_success_data(
        api_client.create_product(
            create_product_payload(product_code=product_code, name=name), ACT1
        )
    )


def create_profile(product_id: str, state_code: str = "CA", **overrides) -> dict:
    return get_success_data(
        api_client.create_profile(
            create_profile_payload(product_id, state_code, **overrides), OFFICER
        )
    )


def create_indication(product_id: str, expected_product_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_indication(
            create_indication_payload(product_id, expected_product_version, **overrides),
            ACT1,
        )
    )


def walk_indication_to_locked(indication_id: str) -> dict:
    """DRAFT -> IN_ACTUARIAL_REVIEW -> APPROVED -> LOCKED (PRD §3.2).

    The preparer (act-1) submits; a different actuary (act-2) approves, per
    segregation of duties."""
    get_success_data(api_client.submit_indication_review(indication_id, ACT1))
    get_success_data(api_client.approve_indication(indication_id, ACT2))
    return get_success_data(api_client.lock_indication(indication_id, ACT2))


def create_locked_indication(product: dict, **indication_overrides) -> dict:
    """Create an indication against the product's current version, then lock it."""
    indication = create_indication(
        product["id"], product["version"], **indication_overrides
    )
    return walk_indication_to_locked(indication["id"])


def create_filing(
    product_id: str, state_code: str, indication_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_filing(
            create_filing_payload(product_id, state_code, indication_id, **overrides),
            ANALYST,
        )
    )


def add_final_component(
    filing_id: str,
    component_type: str = "RATE",
    name: str = "Base Rates",
    content_ref: str = "s3://fil/rate.pdf",
) -> dict:
    component = get_success_data(
        api_client.create_component(
            filing_id,
            create_component_payload(
                component_type=component_type, name=name, content_ref=content_ref
            ),
            ANALYST,
        )
    )
    return get_success_data(api_client.finalize_component(component["id"], ANALYST))


def create_policy(
    product_id: str,
    state_code: str,
    policy_number: str,
    current_premium_cents: int,
    class_rel_factor: float,
    renewal_effective_date: str,
) -> dict:
    return get_success_data(
        api_client.create_policy(
            create_policy_payload(
                product_id,
                state_code=state_code,
                policy_number=policy_number,
                current_premium_cents=current_premium_cents,
                class_rel_factor=class_rel_factor,
                renewal_effective_date=renewal_effective_date,
            ),
            LEAD,
        )
    )


def create_wave(
    filing_id: str,
    wave_start_date: str = "2026-11-16",
    wave_end_date: str = "2026-12-15",
    cap_pct: float = 0.15,
) -> dict:
    return get_success_data(
        api_client.create_wave(
            create_wave_payload(
                filing_id,
                wave_start_date=wave_start_date,
                wave_end_date=wave_end_date,
                cap_pct=cap_pct,
            ),
            LEAD,
        )
    )


def create_deviation(filing_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_deviation(
            create_deviation_payload(filing_id, **overrides), ANALYST
        )
    )


def raise_objection(filing_id: str, question_text: str = "Justify the filing.") -> dict:
    return get_success_data(
        api_client.create_objection(
            create_objection_payload(filing_id, question_text=question_text), REGULATOR
        )
    )


def draft_response(
    objection_id: str, expected_objection_version: int, text: str = "See exhibits."
) -> dict:
    return get_success_data(
        api_client.draft_response(
            objection_id,
            create_response_payload(text, expected_objection_version),
            ANALYST,
        )
    )


def submit_response(response_id: str) -> dict:
    return get_success_data(api_client.submit_response(response_id, OFFICER))


def list_calendar_entries(**params) -> List[dict]:
    """Filtered calendar listing (PRD §2.3, §2.9); returns the data array."""
    data, _meta = validate_paginated(
        api_client.list_calendar_entries(OFFICER, params=params)
    )
    return data


def find_calendar_entry(**params) -> dict:
    """Exactly one calendar entry must match the filter."""
    entries = list_calendar_entries(**params)
    assert len(entries) == 1, (
        f"expected exactly one calendar entry for {params}, got {len(entries)}"
    )
    return entries[0]


# ─── Tier 2/3: filing lifecycle composites ──────────────────────────

def setup_draft_filing(
    state_code: str = "CA",
    filing_type: str = "RATE_CHANGE",
    proposed_change_pct: float = 0.10,
    proposed_effective_date: str = "2026-10-01",
    profile_overrides: Optional[dict] = None,
    indication_overrides: Optional[dict] = None,
) -> dict:
    """Product + state profile + LOCKED indication + DRAFT filing (PRD §3.1–3.3)."""
    product = create_product()
    profile = create_profile(
        product["id"], state_code, **(profile_overrides or {})
    )
    indication = create_locked_indication(product, **(indication_overrides or {}))
    filing = create_filing(
        product["id"],
        state_code,
        indication["id"],
        filing_type=filing_type,
        proposed_change_pct=proposed_change_pct,
        proposed_effective_date=proposed_effective_date,
    )
    return {
        "product": product,
        "profile": profile,
        "indication": indication,
        "filing": filing,
        "components": [],
    }


def setup_ready_filing(
    state_code: str = "CA",
    component_types: Tuple[str, ...] = ("RATE",),
    **kwargs,
) -> dict:
    """DRAFT filing + the given components FINAL + filing marked READY (PRD §3.3)."""
    scenario = setup_draft_filing(state_code=state_code, **kwargs)
    components = [
        add_final_component(
            scenario["filing"]["id"],
            component_type=ctype,
            name=f"{state_code} {ctype} Pages",
            content_ref=f"s3://fil/{state_code.lower()}-{ctype.lower()}.pdf",
        )
        for ctype in component_types
    ]
    scenario["components"] = components
    scenario["filing"] = get_success_data(
        api_client.mark_filing_ready(scenario["filing"]["id"], ANALYST)
    )
    return scenario


def setup_submitted_filing(state_code: str = "CA", **kwargs) -> dict:
    """READY filing submitted by the compliance officer (PRD §3.3)."""
    scenario = setup_ready_filing(state_code=state_code, **kwargs)
    scenario["filing"] = get_success_data(
        api_client.submit_filing(scenario["filing"]["id"], OFFICER)
    )
    return scenario


def setup_approved_filing(
    state_code: str = "CA",
    approve_at: str = "2026-09-01T00:00:00Z",
    **kwargs,
) -> dict:
    """SUBMITTED filing approved by the regulator at the given instant (PRD §3.5)."""
    scenario = setup_submitted_filing(state_code=state_code, **kwargs)
    set_clock(approve_at)
    scenario["filing"] = get_success_data(
        api_client.approve_filing(scenario["filing"]["id"], REGULATOR)
    )
    return scenario


def setup_effective_filing(
    state_code: str = "CA",
    approve_at: str = "2026-09-01T00:00:00Z",
    effective_clock: Optional[str] = None,
    **kwargs,
) -> dict:
    """APPROVED filing marked effective once the clock reaches its actual date
    (PRD §3.5). effective_clock defaults to the resolved actual_effective_date."""
    scenario = setup_approved_filing(state_code=state_code, approve_at=approve_at, **kwargs)
    actual = scenario["filing"]["actual_effective_date"]
    set_clock(effective_clock or f"{actual}T00:00:00Z")
    scenario["filing"] = get_success_data(
        api_client.mark_filing_effective(scenario["filing"]["id"], OFFICER)
    )
    return scenario


# ─── Tier 4: wave / renewal-book composites ─────────────────────────

def setup_effective_with_wave(
    policies: List[Tuple[str, int, float, str]] = (),
    wave_start_date: str = "2026-11-16",
    wave_end_date: str = "2026-12-15",
    cap_pct: float = 0.15,
    state_code: str = "CA",
    profile_overrides: Optional[dict] = None,
    approve_at: str = "2026-09-01T00:00:00Z",
    **filing_kwargs,
) -> dict:
    """EFFECTIVE filing + onboarded PENDING policies + a SCHEDULED wave.

    policies: list of (policy_number, current_premium_cents, class_rel_factor,
    renewal_effective_date) tuples."""
    scenario = setup_effective_filing(
        state_code=state_code,
        profile_overrides=profile_overrides,
        approve_at=approve_at,
        **filing_kwargs,
    )
    scenario["policies"] = [
        create_policy(
            scenario["product"]["id"], state_code, number, premium, rel, renewal
        )
        for number, premium, rel, renewal in policies
    ]
    scenario["wave"] = create_wave(
        scenario["filing"]["id"],
        wave_start_date=wave_start_date,
        wave_end_date=wave_end_date,
        cap_pct=cap_pct,
    )
    return scenario


def setup_released_wave(
    policies: List[Tuple[str, int, float, str]] = (),
    **kwargs,
) -> dict:
    """EFFECTIVE filing + policies + wave released (PRD §3.7)."""
    scenario = setup_effective_with_wave(policies=policies, **kwargs)
    scenario["wave"] = get_success_data(
        api_client.release_wave(scenario["wave"]["id"], LEAD)
    )
    return scenario


def refresh_policy(policy_id: str) -> dict:
    return get_success_data(api_client.get_policy(policy_id, LEAD))


def refresh_wave(wave_id: str) -> dict:
    return get_success_data(api_client.get_wave(wave_id, LEAD))


def refresh_filing(filing_id: str) -> dict:
    return get_success_data(api_client.get_filing(filing_id, OFFICER))


def refresh_objection(objection_id: str) -> dict:
    return get_success_data(api_client.get_objection(objection_id, OFFICER))
