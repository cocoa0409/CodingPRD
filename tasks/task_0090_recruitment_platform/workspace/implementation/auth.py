"""Authentication, RBAC, and HR-binding helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from flask import request

from errors import (
    ApiError,
    ERR_AUTH_INVALID_ROLE,
    ERR_AUTH_MISSING,
    ERR_FORBIDDEN,
    ERR_HR_NOT_BOUND,
    raise_err,
)
from store import store


VALID_ROLES = {
    "HrUser",
    "HiringManager",
    "HrApprover",
    "FinanceApprover",
    "Candidate",
    "HeadhunterUser",
    "PlatformAdmin",
}

HR_SIDE_ROLES = {"HrUser", "HiringManager", "HrApprover", "FinanceApprover"}


@dataclass
class Caller:
    role: str
    user_id: str

    @property
    def is_hr_side(self) -> bool:
        return self.role in HR_SIDE_ROLES

    def hr_user(self) -> Optional[dict]:
        if not self.is_hr_side:
            return None
        return store.hr_users.get(self.user_id)

    def candidate(self) -> Optional[dict]:
        if self.role != "Candidate":
            return None
        return store.candidates.get(self.user_id)

    def headhunter_contract(self) -> Optional[dict]:
        if self.role != "HeadhunterUser":
            return None
        return store.headhunter_contracts.get(self.user_id)


def get_caller() -> Caller:
    role = request.headers.get("X-User-Role", "").strip()
    uid = request.headers.get("X-User-ID", "").strip()
    if not role or not uid:
        raise_err(ERR_AUTH_MISSING)
    if role not in VALID_ROLES:
        raise_err(ERR_AUTH_INVALID_ROLE)
    return Caller(role=role, user_id=uid)


def require_roles(caller: Caller, allowed: Iterable[str]) -> None:
    if caller.role not in set(allowed):
        raise_err(ERR_FORBIDDEN)


def require_hr_bound_to_company(caller: Caller, company_id: str) -> dict:
    """For an HR-side caller, verify the acting HrUser is ACTIVE-bound to company_id."""
    if not caller.is_hr_side:
        raise_err(ERR_FORBIDDEN)
    hr_row = store.hr_users.get(caller.user_id)
    if hr_row is None:
        # HR-side caller asserting an identity that does not exist.
        raise_err(ERR_HR_NOT_BOUND)
    if hr_row.get("company_id") != company_id:
        raise_err(ERR_HR_NOT_BOUND)
    if hr_row.get("binding_status") != "ACTIVE":
        raise_err(ERR_HR_NOT_BOUND)
    return hr_row
