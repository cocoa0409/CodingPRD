"""JurisdictionPolicy upsert service."""
from __future__ import annotations

from core.errors import err_validation_failed
from core.store import store
from services.timestamps import stamp_create


_VALID_CODES = {"CA", "NY", "IL", "TX", "FL", "MA", "WA"}
_VALID_BTB = {"POST_OFFER", "POST_INTERVIEW", "PRE_OFFER"}


def upsert_jurisdiction(code: str, body: dict) -> dict:
    if code not in _VALID_CODES:
        raise err_validation_failed(
            "jurisdiction_code must be one of CA, NY, IL, TX, FL, MA, WA."
        )

    cl = body.get("criminal_lookback_years")
    sb = body.get("salary_history_ban")
    btb = body.get("ban_the_box_stage")
    wd = body.get("adverse_action_waiting_business_days")

    if isinstance(cl, bool) or not isinstance(cl, int) or cl < 0:
        raise err_validation_failed(
            "criminal_lookback_years must be a non-negative integer."
        )
    if not isinstance(sb, bool):
        raise err_validation_failed("salary_history_ban must be a boolean.")
    if not isinstance(btb, str) or btb not in _VALID_BTB:
        raise err_validation_failed(
            "ban_the_box_stage must be one of POST_OFFER, POST_INTERVIEW, PRE_OFFER."
        )
    if isinstance(wd, bool) or not isinstance(wd, int) or wd < 5:
        raise err_validation_failed(
            "adverse_action_waiting_business_days must be an integer >= 5."
        )

    existing = store.jurisdiction_policies.get(code)
    if existing is None:
        row = {
            "jurisdiction_code": code,
            "criminal_lookback_years": cl,
            "salary_history_ban": sb,
            "ban_the_box_stage": btb,
            "adverse_action_waiting_business_days": wd,
        }
        stamp_create(row, with_version=False)
        store.jurisdiction_policies[code] = row
        return row
    existing["criminal_lookback_years"] = cl
    existing["salary_history_ban"] = sb
    existing["ban_the_box_stage"] = btb
    existing["adverse_action_waiting_business_days"] = wd
    return existing
