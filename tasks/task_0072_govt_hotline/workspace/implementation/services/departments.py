"""Department service."""

from errors import AppError, ERR_VALIDATION, ERR_RESOURCE_NOT_FOUND, ERR_VERSION_CONFLICT, ERROR_STATUS
import db
import validators as V


VALID_STATUSES = {"ACTIVE", "SUSPENDED"}


def create_department(body: dict) -> dict:
    name = V.is_str(body, "name", min_len=1, max_len=120)
    code = V.is_str(body, "code", min_len=2, max_len=40, pattern=V.DEPT_CODE_RE)
    jurisdiction_codes = V.is_list(body, "jurisdiction_codes")
    for j in jurisdiction_codes:
        if not isinstance(j, str):
            raise AppError(ERR_VALIDATION, "jurisdiction_codes must be strings", ERROR_STATUS[ERR_VALIDATION])
        import re
        if not re.fullmatch(V.JURISDICTION_RE, j):
            raise AppError(ERR_VALIDATION, f"jurisdiction_code {j} invalid", ERROR_STATUS[ERR_VALIDATION])
    jurisdiction_codes = sorted(set(jurisdiction_codes), key=jurisdiction_codes.index)
    # dedupe preserving order
    seen = set()
    deduped = []
    for j in jurisdiction_codes:
        if j not in seen:
            seen.add(j)
            deduped.append(j)
    jurisdiction_codes = deduped

    category_codes = V.is_list(body, "category_codes", optional=True, default=[])
    # validate each category code exists in CategoryRule (any sub-cat with that category)
    for cc in category_codes:
        if not isinstance(cc, str):
            raise AppError(ERR_VALIDATION, "category_codes must be strings", ERROR_STATUS[ERR_VALIDATION])
    seen = set()
    deduped_cc = []
    for c in category_codes:
        if c not in seen:
            seen.add(c)
            deduped_cc.append(c)
    category_codes = deduped_cc

    status = V.is_enum(body, "status", VALID_STATUSES, optional=True, default="ACTIVE")

    # code uniqueness
    if db.find_one("departments", code=code) is not None:
        raise AppError(ERR_VALIDATION, f"department code {code} already exists", ERROR_STATUS[ERR_VALIDATION])

    rec = db.insert("departments", {
        "name": name,
        "code": code,
        "jurisdiction_codes": list(jurisdiction_codes),
        "category_codes": list(category_codes),
        "status": status,
        "pending_work_count": 0,
    })
    return rec


def get_department(dept_id: str) -> dict:
    d = db.find_by_id("departments", dept_id)
    if not d:
        raise AppError(ERR_RESOURCE_NOT_FOUND, "Department not found", ERROR_STATUS[ERR_RESOURCE_NOT_FOUND])
    return d


def update_department(dept_id: str, body: dict) -> dict:
    d = get_department(dept_id)
    # OCC priority 22
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(d.get("version", 0)):
            raise AppError(ERR_VERSION_CONFLICT, "Version conflict", ERROR_STATUS[ERR_VERSION_CONFLICT])

    updates = {}
    if "name" in body and body["name"] is not None:
        updates["name"] = V.is_str(body, "name", min_len=1, max_len=120)
    if "jurisdiction_codes" in body and body["jurisdiction_codes"] is not None:
        jcs = V.is_list(body, "jurisdiction_codes")
        import re
        for j in jcs:
            if not isinstance(j, str) or not re.fullmatch(V.JURISDICTION_RE, j):
                raise AppError(ERR_VALIDATION, "invalid jurisdiction_code", ERROR_STATUS[ERR_VALIDATION])
        seen = set()
        deduped = []
        for j in jcs:
            if j not in seen:
                seen.add(j)
                deduped.append(j)
        updates["jurisdiction_codes"] = deduped
    if "category_codes" in body and body["category_codes"] is not None:
        ccs = V.is_list(body, "category_codes")
        for c in ccs:
            if not isinstance(c, str):
                raise AppError(ERR_VALIDATION, "category_codes must be strings", ERROR_STATUS[ERR_VALIDATION])
        seen = set()
        deduped = []
        for c in ccs:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        updates["category_codes"] = deduped
    if "status" in body and body["status"] is not None:
        updates["status"] = V.is_enum(body, "status", VALID_STATUSES)

    if updates:
        db.update_fields(d, updates)
    return d


def list_departments(limit: int, offset: int, status=None, jurisdiction_code=None) -> tuple[list[dict], int]:
    rows = list(db.all_rows("departments"))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if jurisdiction_code is not None:
        rows = [r for r in rows if jurisdiction_code in r.get("jurisdiction_codes", [])]
    rows = sorted(rows, key=lambda r: r["created_at"])
    total = len(rows)
    return rows[offset: offset + limit], total
