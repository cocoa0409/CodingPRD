"""CoveragePart endpoints (PRD 3.2)."""
from flask import Blueprint

import lookup
from db import by_policy, new_row, store, touch
from enums import CONDITION_CODES, PART_TYPES
from errors import ApiError
from middleware import authenticate, body, get_enum, get_int, present
from response import created, ok

bp = Blueprint("coverage_parts", __name__)

EDITABLE_POLICY_STATUSES = ("DRAFT", "REFERRED")


@bp.post("/coverage-parts")
def schedule_coverage_part():
    authenticate("Underwriter")
    payload = body()
    policy = lookup.fk_policy(payload)
    part_type = get_enum(payload, "part_type", PART_TYPES)
    sublimit_cents = get_int(payload, "sublimit_cents", minimum=1)
    condition_code = get_enum(
        payload, "condition_code", CONDITION_CODES, required=False, default="NONE"
    )
    if policy["status"] not in EDITABLE_POLICY_STATUSES:
        raise ApiError(
            "ERR_INVALID_POLICY_STATE",
            "The coverage schedule is editable only while the policy is DRAFT or REFERRED.",
        )
    if part_type == "EXISTING_STRUCTURE" and not policy["includes_existing_structure"]:
        raise ApiError(
            "ERR_COVERAGE_PART_NOT_PERMITTED",
            "An EXISTING_STRUCTURE part requires includes_existing_structure to be true.",
        )
    if part_type == "DELAY_IN_COMPLETION" and policy["daily_delay_rate_cents"] <= 0:
        raise ApiError(
            "ERR_COVERAGE_PART_NOT_PERMITTED",
            "A DELAY_IN_COMPLETION part requires a positive daily_delay_rate_cents.",
        )
    existing = by_policy(store.coverage_parts, policy["id"])
    if any(part["part_type"] == part_type for part in existing):
        raise ApiError(
            "ERR_DUPLICATE_COVERAGE_PART", "This part_type is already scheduled on the policy."
        )
    active_sum = sum(part["sublimit_cents"] for part in existing if part["status"] == "ACTIVE")
    if active_sum + sublimit_cents > policy["limit_cents"]:
        raise ApiError(
            "ERR_SUBLIMIT_EXCEEDS_LIMIT",
            "The scheduled sublimits would exceed the policy aggregate limit.",
        )
    row = new_row()
    row.update({
        "policy_id": policy["id"],
        "part_type": part_type,
        "sublimit_cents": sublimit_cents,
        "condition_code": condition_code,
        "eroded_cents": 0,
        "available_cents": sublimit_cents,
        "status": "ACTIVE",
    })
    store.coverage_parts[row["id"]] = row
    touch(policy)
    return created(row)


@bp.patch("/coverage-parts/<part_id>")
def patch_coverage_part(part_id):
    authenticate("Underwriter")
    part = lookup.coverage_part(part_id)
    payload = body()
    has_sublimit = present(payload, "sublimit_cents")
    has_condition = present(payload, "condition_code")
    if not has_sublimit and not has_condition:
        raise ApiError(
            "ERR_INVALID_REQUEST", "A patch must revise sublimit_cents, condition_code, or both."
        )
    sublimit_cents = get_int(payload, "sublimit_cents", required=False, minimum=1)
    condition_code = get_enum(payload, "condition_code", CONDITION_CODES, required=False)
    policy = store.policies[part["policy_id"]]
    if policy["status"] not in EDITABLE_POLICY_STATUSES:
        raise ApiError(
            "ERR_INVALID_POLICY_STATE",
            "The coverage schedule is editable only while the policy is DRAFT or REFERRED.",
        )
    if has_sublimit:
        active_sum = 0
        for other in by_policy(store.coverage_parts, policy["id"]):
            if other["status"] != "ACTIVE":
                continue
            active_sum += sublimit_cents if other["id"] == part["id"] else other["sublimit_cents"]
        if active_sum > policy["limit_cents"]:
            raise ApiError(
                "ERR_SUBLIMIT_EXCEEDS_LIMIT",
                "The scheduled sublimits would exceed the policy aggregate limit.",
            )
        part["sublimit_cents"] = sublimit_cents
    if has_condition:
        part["condition_code"] = condition_code
    part["available_cents"] = part["sublimit_cents"] - part["eroded_cents"]
    touch(part)
    return ok(part)


@bp.get("/coverage-parts/<part_id>")
def read_coverage_part(part_id):
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer", "ClaimAdjuster")
    return ok(lookup.coverage_part(part_id))
