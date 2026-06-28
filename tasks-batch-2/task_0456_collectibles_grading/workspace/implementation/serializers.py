"""Entity field projections (scaffold §1.1).

Each serializer returns exactly the fields declared for that entity plus the
common fields. Internal bookkeeping keys (prefixed with `_`) are never exposed.
"""

COMMON = ["id", "created_at", "updated_at", "version"]


def _project(record, fields):
    out = {}
    for f in fields:
        out[f] = record.get(f)
    return out


def customer(r):
    return _project(r, COMMON + ["email", "full_name", "store_credit_cents"])


def service_level(r):
    return _project(
        r,
        COMMON
        + [
            "code",
            "turnaround_business_days",
            "base_fee_cents",
            "max_declared_value_cents",
            "insurance_rate_bps",
            "active",
        ],
    )


def grading_standard(r):
    return _project(
        r,
        COMMON
        + [
            "code",
            "max_grade",
            "authentic_min_grade",
            "centering_weight_bps",
            "corners_weight_bps",
            "edges_weight_bps",
            "surface_weight_bps",
        ],
    )


def submission(r):
    return _project(
        r,
        COMMON
        + [
            "customer_id",
            "service_level_id",
            "status",
            "item_count",
            "total_estimated_fee_cents",
            "total_final_fee_cents",
        ],
    )


def submission_item(r):
    return _project(
        r,
        COMMON
        + [
            "submission_id",
            "grading_standard_id",
            "title",
            "declared_value_cents",
            "status",
            "estimated_fee_cents",
            "final_fee_cents",
            "regrade_count",
            "current_grade",
        ],
    )


def intake_record(r):
    return _project(
        r,
        COMMON
        + [
            "item_id",
            "received_by_user_id",
            "condition_note",
            "matches_declaration",
            "received_at",
        ],
    )


def grade_assessment(r):
    return _project(
        r,
        COMMON
        + [
            "item_id",
            "grading_standard_id",
            "centering_subgrade",
            "corners_subgrade",
            "edges_subgrade",
            "surface_subgrade",
            "provisional_overall",
            "final_overall",
            "superseded",
        ],
    )


def authentication_check(r):
    return _project(
        r,
        COMMON + ["item_id", "authenticator_user_id", "verdict", "alteration_note"],
    )


def slab(r):
    return _project(
        r,
        COMMON
        + [
            "item_id",
            "cert_number",
            "assessment_id",
            "label_grade_text",
            "active",
        ],
    )


def label(r):
    # Label is immutable: only id + created_at (no updated_at, no version).
    return _project(
        r,
        ["id", "created_at"]
        + ["slab_id", "population_report_id", "printed_pop_count", "printed_at"],
    )


def population_report(r):
    return _project(
        r,
        COMMON + ["grading_standard_id", "title_key", "grade_value", "pop_count"],
    )


def insurance_policy(r):
    return _project(
        r,
        COMMON
        + [
            "submission_id",
            "covered_value_cents",
            "premium_cents",
            "claim_status",
            "payout_cents",
        ],
    )


def regrade_request(r):
    return _project(
        r,
        COMMON
        + [
            "item_id",
            "prior_slab_id",
            "expected_item_version",
            "reason",
            "status",
        ],
    )


def shipment(r):
    return _project(
        r,
        COMMON
        + [
            "submission_id",
            "carrier",
            "tracking_number",
            "insured_value_cents",
            "status",
        ],
    )
