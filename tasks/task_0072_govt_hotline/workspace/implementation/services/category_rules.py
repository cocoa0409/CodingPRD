"""CategoryRule service."""

from errors import (
    AppError, ERR_VALIDATION, ERR_REFERENCE_NOT_FOUND, ERR_CATEGORY_UNKNOWN, ERROR_STATUS,
)
import db
import validators as V


def create_category_rule(body: dict) -> dict:
    category_code = V.is_str(body, "category_code", min_len=2, max_len=30, pattern=V.CATEGORY_RE)
    sub_category_code = V.is_str(body, "sub_category_code", min_len=2, max_len=30, pattern=V.CATEGORY_RE)
    lead_code = V.is_str(body, "lead_department_code", min_len=2, max_len=40, pattern=V.DEPT_CODE_RE)
    supporting_codes = V.is_list(body, "supporting_department_codes", optional=True, default=[])
    for c in supporting_codes:
        if not isinstance(c, str):
            raise AppError(ERR_VALIDATION, "supporting_department_codes must be strings",
                           ERROR_STATUS[ERR_VALIDATION])

    statutory = V.is_int(body, "statutory_time_limit_hours", min_v=1, max_v=1440)
    committed = V.is_int(body, "committed_time_limit_hours", min_v=1, max_v=1440)
    if committed > statutory:
        raise AppError(
            ERR_VALIDATION,
            "committed_time_limit_hours must be <= statutory_time_limit_hours",
            ERROR_STATUS[ERR_VALIDATION],
        )
    difficulty_base = V.is_int(body, "difficulty_base", min_v=1, max_v=5, optional=True, default=1)

    # uniqueness of (category_code, sub_category_code)
    if db.find_one("category_rules", category_code=category_code, sub_category_code=sub_category_code):
        raise AppError(ERR_VALIDATION, "category_code+sub_category_code already exists",
                       ERROR_STATUS[ERR_VALIDATION])

    # lead_department_code must reference an existing ACTIVE department
    lead_dept = db.find_one("departments", code=lead_code)
    if lead_dept is None:
        raise AppError(ERR_REFERENCE_NOT_FOUND, "lead_department_code does not resolve",
                       ERROR_STATUS[ERR_REFERENCE_NOT_FOUND])
    if lead_dept["status"] != "ACTIVE":
        raise AppError(ERR_REFERENCE_NOT_FOUND, "lead department not ACTIVE",
                       ERROR_STATUS[ERR_REFERENCE_NOT_FOUND])

    # Each supporting code must reference an existing department, not include lead code, deduped.
    if lead_code in supporting_codes:
        raise AppError(ERR_VALIDATION, "supporting_department_codes must not include lead",
                       ERROR_STATUS[ERR_VALIDATION])
    seen = set()
    deduped = []
    for c in supporting_codes:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    supporting_codes = deduped
    for c in supporting_codes:
        if db.find_one("departments", code=c) is None:
            raise AppError(ERR_REFERENCE_NOT_FOUND, f"supporting department {c} does not resolve",
                           ERROR_STATUS[ERR_REFERENCE_NOT_FOUND])

    rec = db.insert("category_rules", {
        "category_code": category_code,
        "sub_category_code": sub_category_code,
        "lead_department_code": lead_code,
        "supporting_department_codes": list(supporting_codes),
        "statutory_time_limit_hours": statutory,
        "committed_time_limit_hours": committed,
        "difficulty_base": difficulty_base,
    })
    return rec


def list_category_rules(limit: int, offset: int, category_code=None) -> tuple[list[dict], int]:
    rows = list(db.all_rows("category_rules"))
    if category_code is not None:
        rows = [r for r in rows if r["category_code"] == category_code]
    rows = sorted(rows, key=lambda r: r["created_at"])
    return rows[offset: offset + limit], len(rows)


def find_rule(category_code: str, sub_category_code: str):
    return db.find_one("category_rules", category_code=category_code, sub_category_code=sub_category_code)


def require_rule(category_code: str, sub_category_code: str) -> dict:
    rule = find_rule(category_code, sub_category_code)
    if rule is None:
        raise AppError(ERR_CATEGORY_UNKNOWN, "category pair unknown", ERROR_STATUS[ERR_CATEGORY_UNKNOWN])
    return rule
