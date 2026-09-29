"""Composite state builders.

Every builder starts from an empty database and drives only the public API, so a
test can compose exactly the preconditions it needs. Builders return a mutable
`program` dictionary that later builders extend, and they thread the real entity
identifier into every entity-backed role header.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    CANONICAL_RUBRIC_ITEMS,
    CLOCK_EPOCH,
    SCORE_SHEET_ONE_CRITICAL,
    SCORE_SHEET_SHADOW,
    SCORE_SHEET_TWO_CRITICAL,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_auditor_headers,
    make_calibration_reviewer_headers,
    make_franchisee_headers,
)

ADMIN_HEADERS = TEST_USERS["brand_admin_headers"]
INTEGRATOR_HEADERS = TEST_USERS["compliance_integrator_headers"]

# The canonical calendar used by the builders.
FIRST_VISIT_START = "2026-08-05T09:00:00Z"
FIRST_VISIT_END = "2026-08-05T13:00:00Z"
SECOND_VISIT_START = "2026-08-20T09:00:00Z"
SECOND_VISIT_END = "2026-08-20T13:00:00Z"
SHADOW_VISIT_START = "2026-08-06T09:00:00Z"
SHADOW_VISIT_END = "2026-08-06T13:00:00Z"
HEALTH_INSPECTION_DATE = "2026-07-20T00:00:00Z"
# Derived deadlines of the corrective actions raised by a visit finalized at
# FIRST_VISIT_END: 72 hours for CRITICAL, 14 days for STANDARD.
CRITICAL_ACTION_DUE_AT = "2026-08-08T13:00:00Z"
STANDARD_ACTION_DUE_AT = "2026-08-19T13:00:00Z"
# A moment after the CRITICAL deadline but before the STANDARD one.
AFTER_CRITICAL_DEADLINE = "2026-08-09T00:00:00Z"


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def advance_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock and return the reported reading."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or ADMIN_HEADERS))


# --------------------------------------------------------------------------
# Tier 2 — single records and the entity hierarchy
# --------------------------------------------------------------------------
def create_brand(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_brand(f.brand_payload(**overrides), headers or ADMIN_HEADERS)
    )


def create_franchisee(brand_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_franchisee(
            f.franchisee_payload(brand_id, **overrides), headers or ADMIN_HEADERS
        )
    )


def create_location(brand_id, franchisee_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_location(
            f.location_payload(brand_id, franchisee_id, **overrides),
            headers or ADMIN_HEADERS,
        )
    )


def create_auditor(headers=None, **overrides) -> dict:
    """A freshly created auditor, left in its initial state."""
    return get_success_data(
        api_client.create_auditor(f.auditor_payload(**overrides), headers or ADMIN_HEADERS)
    )


def create_certified_auditor(headers=None, **overrides) -> dict:
    auditor = create_auditor(headers, **overrides)
    return get_success_data(
        api_client.certify_auditor(auditor["id"], headers or ADMIN_HEADERS, {})
    )


def create_health_inspection(location_id, points_scored, letter_grade,
                             inspection_date=HEALTH_INSPECTION_DATE,
                             points_possible=100, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_health_inspection(
            f.health_inspection_payload(
                location_id, inspection_date, points_scored, letter_grade,
                points_possible=points_possible, **overrides,
            ),
            headers or INTEGRATOR_HEADERS,
        )
    )


def live_brand_version(brand_id, headers=None) -> int:
    """The brand's current version, for the optimistic-concurrency token."""
    return get_success_data(api_client.get_brand(brand_id, headers or ADMIN_HEADERS))["version"]


def create_rubric_draft(brand_id, expected_brand_version=None, headers=None, **overrides) -> dict:
    headers = headers or ADMIN_HEADERS
    if expected_brand_version is None:
        expected_brand_version = live_brand_version(brand_id, headers)
    return get_success_data(
        api_client.create_rubric_version(
            f.rubric_version_payload(brand_id, expected_brand_version, **overrides), headers
        )
    )


def add_rubric_items(rubric_version_id, items=None, headers=None) -> dict:
    """Create the given rubric items and return them keyed by `item_code`."""
    headers = headers or ADMIN_HEADERS
    created = {}
    for spec in (items if items is not None else CANONICAL_RUBRIC_ITEMS):
        created[spec["item_code"]] = get_success_data(
            api_client.create_rubric_item(
                rubric_version_id,
                f.rubric_item_payload(
                    spec["item_code"], spec["section"], spec["max_points"],
                    spec["display_order"], is_critical=spec["is_critical"],
                ),
                headers,
            )
        )
    return created


def create_published_rubric(brand_id, items=None, headers=None, **overrides):
    """A published rubric version plus its items keyed by `item_code`."""
    headers = headers or ADMIN_HEADERS
    rubric = create_rubric_draft(brand_id, headers=headers, **overrides)
    created_items = add_rubric_items(rubric["id"], items, headers)
    rubric = get_success_data(api_client.publish_rubric_version(rubric["id"], headers, {}))
    return rubric, created_items


# --------------------------------------------------------------------------
# Tier 2 — the whole audit program a visit needs
# --------------------------------------------------------------------------
def setup_brand_program(with_reviewer=False, publish_rubric=True, rubric_items=None,
                        health_points=None, health_grade=None,
                        health_date=HEALTH_INSPECTION_DATE,
                        clock=CLOCK_EPOCH, brand_overrides=None,
                        franchisee_overrides=None, location_overrides=None,
                        auditor_overrides=None) -> dict:
    """Brand, franchisee, location, certified auditor and a rubric version.

    `publish_rubric=False` leaves the rubric version in its initial state.
    Supplying `health_points` and `health_grade` records one health inspection.
    """
    advance_clock(clock)
    brand = create_brand(**(brand_overrides or {}))
    franchisee = create_franchisee(brand["id"], **(franchisee_overrides or {}))
    location = create_location(
        brand["id"], franchisee["id"], **(location_overrides or {})
    )

    health_inspection = None
    if health_points is not None and health_grade is not None:
        health_inspection = create_health_inspection(
            location["id"], health_points, health_grade, inspection_date=health_date,
        )

    auditor = create_certified_auditor(**(auditor_overrides or {}))
    reviewer = None
    if with_reviewer:
        reviewer = create_certified_auditor(
            full_name=TEST_DEFAULTS["REVIEWER_NAME"],
            employee_code=TEST_DEFAULTS["REVIEWER_CODE"],
        )

    if publish_rubric:
        rubric_version, items = create_published_rubric(brand["id"], rubric_items)
    else:
        rubric_version = create_rubric_draft(brand["id"])
        items = add_rubric_items(rubric_version["id"], rubric_items)

    program = {
        "admin_headers": ADMIN_HEADERS,
        "integrator_headers": INTEGRATOR_HEADERS,
        "brand": brand,
        "franchisee": franchisee,
        "franchisee_headers": make_franchisee_headers(franchisee["id"]),
        "location": location,
        "auditor": auditor,
        "auditor_headers": make_auditor_headers(auditor["id"]),
        "reviewer": reviewer,
        "reviewer_headers": (
            make_auditor_headers(reviewer["id"]) if reviewer else None
        ),
        "reviewer_calibration_headers": (
            make_calibration_reviewer_headers(reviewer["id"]) if reviewer else None
        ),
        "health_inspection": health_inspection,
        "rubric_version": rubric_version,
        "items": items,
        "item_ids": {code: item["id"] for code, item in items.items()},
        "visits": [],
        "scored_items": {},
        "corrective_actions": {},
    }
    return program


# --------------------------------------------------------------------------
# Tier 1 — visit state progression
# --------------------------------------------------------------------------
def schedule_visit(program, start_at=FIRST_VISIT_START, end_at=FIRST_VISIT_END,
                   visit_type="UNANNOUNCED", auditor_id=None, location_id=None,
                   rubric_version_id=None, headers=None, **overrides) -> dict:
    visit = get_success_data(
        api_client.create_audit_visit(
            f.audit_visit_payload(
                location_id or program["location"]["id"],
                auditor_id or program["auditor"]["id"],
                rubric_version_id or program["rubric_version"]["id"],
                start_at, end_at, visit_type=visit_type, **overrides,
            ),
            headers or ADMIN_HEADERS,
        )
    )
    program["visits"].append(visit)
    return visit


def start_visit(program, visit_id, at=None, auditor_id=None) -> dict:
    if at is not None:
        advance_clock(at)
    headers = make_auditor_headers(auditor_id or program["auditor"]["id"])
    return get_success_data(api_client.start_audit_visit(visit_id, headers, {}))


def score_visit(program, visit_id, sheet=None, auditor_id=None) -> dict:
    """Score every item of the sheet and return the rows keyed by `item_code`."""
    headers = make_auditor_headers(auditor_id or program["auditor"]["id"])
    sheet = SCORE_SHEET_ONE_CRITICAL if sheet is None else sheet
    scored = {}
    for code, points in sheet.items():
        scored[code] = get_success_data(
            api_client.create_scored_item(
                visit_id, f.scored_item_payload(program["item_ids"][code], points), headers,
            )
        )
    program["scored_items"][visit_id] = scored
    return scored


def submit_visit(program, visit_id, auditor_id=None) -> dict:
    headers = make_auditor_headers(auditor_id or program["auditor"]["id"])
    return get_success_data(api_client.submit_audit_visit(visit_id, headers, {}))


def finalize_visit(program, visit_id, at=None) -> dict:
    if at is not None:
        advance_clock(at)
    return get_success_data(api_client.finalize_audit_visit(visit_id, ADMIN_HEADERS, {}))


def collect_corrective_actions(program, scored_items) -> dict:
    """The corrective action raised for each violating scored item, by `item_code`."""
    actions = {}
    for code, item in scored_items.items():
        rows = get_success_data(
            api_client.list_corrective_actions(
                ADMIN_HEADERS, params={"scored_item_id": item["id"]}
            )
        )
        if rows:
            actions[code] = rows[0]
    program["corrective_actions"].update(actions)
    return actions


# --------------------------------------------------------------------------
# Tier 3 — full-lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_scheduled_visit(program=None, start_at=FIRST_VISIT_START,
                          end_at=FIRST_VISIT_END, visit_type="UNANNOUNCED",
                          **program_kwargs) -> dict:
    program = program or setup_brand_program(**program_kwargs)
    program["visit"] = schedule_visit(
        program, start_at=start_at, end_at=end_at, visit_type=visit_type
    )
    return program


def setup_in_progress_visit(program=None, start_at=FIRST_VISIT_START,
                            end_at=FIRST_VISIT_END, sheet=None,
                            **program_kwargs) -> dict:
    """A started visit, optionally with a score sheet already entered."""
    program = setup_scheduled_visit(
        program, start_at=start_at, end_at=end_at, **program_kwargs
    )
    visit_id = program["visit"]["id"]
    program["visit"] = start_visit(program, visit_id, at=start_at)
    if sheet is not None:
        program["scored"] = score_visit(program, visit_id, sheet)
    return program


def setup_submitted_visit(program=None, sheet=None, start_at=FIRST_VISIT_START,
                          end_at=FIRST_VISIT_END, **program_kwargs) -> dict:
    sheet = SCORE_SHEET_ONE_CRITICAL if sheet is None else sheet
    program = setup_in_progress_visit(
        program, start_at=start_at, end_at=end_at, sheet=sheet, **program_kwargs
    )
    program["visit"] = submit_visit(program, program["visit"]["id"])
    return program


def setup_finalized_visit(program=None, sheet=None, start_at=FIRST_VISIT_START,
                          end_at=FIRST_VISIT_END, finalize_at=None,
                          **program_kwargs) -> dict:
    """A finalized visit plus its corrective actions keyed by `item_code`."""
    program = setup_submitted_visit(
        program, sheet=sheet, start_at=start_at, end_at=end_at, **program_kwargs
    )
    program["visit"] = finalize_visit(
        program, program["visit"]["id"], at=finalize_at or end_at
    )
    program["actions"] = collect_corrective_actions(program, program["scored"])
    return program


def setup_finalized_visit_with_health(points_scored=74, letter_grade="C", **kwargs) -> dict:
    """A finalized visit whose composite admits a health component."""
    return setup_finalized_visit(
        health_points=points_scored, health_grade=letter_grade, **kwargs
    )


# --------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# --------------------------------------------------------------------------
def setup_two_finalized_visits(sheet=None, finalize_second=True) -> dict:
    """Two visits over the same rubric items, so the repeat window is populated.

    The second visit is scheduled before the first is scored, and both carry the
    same sheet, so every critically violated item appears in two finalized visits.
    """
    sheet = SCORE_SHEET_TWO_CRITICAL if sheet is None else sheet
    program = setup_brand_program(health_points=100, health_grade="A")
    first = schedule_visit(program, FIRST_VISIT_START, FIRST_VISIT_END)
    second = schedule_visit(program, SECOND_VISIT_START, SECOND_VISIT_END)

    start_visit(program, first["id"], at=FIRST_VISIT_START)
    first_scored = score_visit(program, first["id"], sheet)
    submit_visit(program, first["id"])
    program["first_visit"] = finalize_visit(program, first["id"], at=FIRST_VISIT_END)

    start_visit(program, second["id"], at=SECOND_VISIT_START)
    second_scored = score_visit(program, second["id"], sheet)
    program["second_visit"] = submit_visit(program, second["id"])
    advance_clock(SECOND_VISIT_END)
    if finalize_second:
        program["second_visit"] = finalize_visit(program, second["id"])

    program["first_scored"] = first_scored
    program["second_scored"] = second_scored
    return program


def setup_escalated_critical_action(sweep_at=AFTER_CRITICAL_DEADLINE) -> dict:
    """A finalized visit whose critical corrective action has been swept overdue."""
    program = setup_finalized_visit_with_health()
    advance_clock(sweep_at)
    program["sweep"] = get_success_data(api_client.run_overdue_sweep(ADMIN_HEADERS, {}))
    return program


def setup_shadow_calibration(record_first=True, with_second_shadow=True,
                             shadow_sheet=None) -> dict:
    """A submitted primary visit plus one or two submitted shadow visits.

    `record_first` writes the calibration record for the first shadow visit, so a
    test can trigger the second one and observe the accumulated reliability.
    `shadow_sheet` chooses how far the shadow scoring sits from the primary one.
    """
    shadow_sheet = SCORE_SHEET_SHADOW if shadow_sheet is None else shadow_sheet
    program = setup_brand_program(with_reviewer=True)
    reviewer_id = program["reviewer"]["id"]
    primary = schedule_visit(program, FIRST_VISIT_START, FIRST_VISIT_END)
    first_shadow = schedule_visit(
        program, FIRST_VISIT_START, FIRST_VISIT_END, visit_type="SHADOW",
        auditor_id=reviewer_id, shadow_of_visit_id=primary["id"],
    )
    second_shadow = None
    if with_second_shadow:
        second_shadow = schedule_visit(
            program, SHADOW_VISIT_START, SHADOW_VISIT_END, visit_type="SHADOW",
            auditor_id=reviewer_id, shadow_of_visit_id=primary["id"],
        )

    start_visit(program, primary["id"], at=FIRST_VISIT_START)
    program["primary_scored"] = score_visit(program, primary["id"], SCORE_SHEET_ONE_CRITICAL)
    program["primary_visit"] = submit_visit(program, primary["id"])

    start_visit(program, first_shadow["id"], auditor_id=reviewer_id)
    score_visit(program, first_shadow["id"], shadow_sheet, auditor_id=reviewer_id)
    program["first_shadow"] = submit_visit(
        program, first_shadow["id"], auditor_id=reviewer_id
    )

    program["calibration_records"] = []
    if record_first:
        program["calibration_records"].append(
            get_success_data(
                api_client.create_calibration_record(
                    f.calibration_record_payload(first_shadow["id"]),
                    program["reviewer_calibration_headers"],
                )
            )
        )

    if second_shadow is not None:
        start_visit(program, second_shadow["id"], at=SHADOW_VISIT_START,
                    auditor_id=reviewer_id)
        score_visit(program, second_shadow["id"], shadow_sheet, auditor_id=reviewer_id)
        program["second_shadow"] = submit_visit(
            program, second_shadow["id"], auditor_id=reviewer_id
        )
    return program


# --------------------------------------------------------------------------
# Tier 5 — remediation and appeal states
# --------------------------------------------------------------------------
def attach_action_photo(program, corrective_action_id,
                        captured_at=FIRST_VISIT_END, **overrides) -> dict:
    return get_success_data(
        api_client.create_evidence_photo(
            f.evidence_photo_payload(
                captured_at, corrective_action_id=corrective_action_id, **overrides
            ),
            program["franchisee_headers"],
        )
    )


def attach_dispute_photo(program, dispute_id,
                         captured_at=FIRST_VISIT_END, **overrides) -> dict:
    return get_success_data(
        api_client.create_evidence_photo(
            f.evidence_photo_payload(captured_at, dispute_id=dispute_id, **overrides),
            program["franchisee_headers"],
        )
    )


def setup_submitted_corrective_action(program=None, item_code="BS-1", **kwargs) -> dict:
    """A corrective action carried to its submitted state with one photo."""
    program = program or setup_finalized_visit(**kwargs)
    action = program["actions"][item_code]
    attach_action_photo(program, action["id"])
    program["action"] = get_success_data(
        api_client.submit_corrective_action(
            action["id"], program["franchisee_headers"],
            {"remediation_note": "Deficiency remediated and photographed."},
        )
    )
    return program


def setup_rejected_corrective_action(program=None, item_code="BS-1", **kwargs) -> dict:
    """A corrective action rejected once, with a second photo already attached."""
    program = setup_submitted_corrective_action(program, item_code, **kwargs)
    action_id = program["action"]["id"]
    program["action"] = get_success_data(
        api_client.verify_corrective_action(
            action_id,
            f.verify_payload("REJECTED", rejection_reason="The photo shows the old fitting."),
            program["auditor_headers"],
        )
    )
    attach_action_photo(program, action_id, captured_at="2026-08-05T12:40:00Z")
    return program


def setup_verified_corrective_action(program=None, item_code="BS-1", **kwargs) -> dict:
    program = setup_submitted_corrective_action(program, item_code, **kwargs)
    program["action"] = get_success_data(
        api_client.verify_corrective_action(
            program["action"]["id"], f.verify_payload("ACCEPTED"),
            program["auditor_headers"],
        )
    )
    return program


def setup_filed_dispute(program=None, item_code="FS-1", requested_points=30,
                        **kwargs) -> dict:
    """A dispute filed against one scored item of a finalized visit."""
    program = program or setup_finalized_visit(**kwargs)
    scored_item = program["scored"][item_code]
    program["disputed_item"] = scored_item
    program["dispute"] = get_success_data(
        api_client.create_dispute(
            f.dispute_payload(scored_item["id"], requested_points),
            program["franchisee_headers"],
        )
    )
    return program


def setup_dispute_in_evidence_review(program=None, item_code="FS-1",
                                     requested_points=30, **kwargs) -> dict:
    """A filed dispute supplemented with one photo, awaiting a decision."""
    program = setup_filed_dispute(program, item_code, requested_points, **kwargs)
    dispute_id = program["dispute"]["id"]
    attach_dispute_photo(program, dispute_id, captured_at="2026-08-05T12:15:00Z")
    program["dispute"] = get_success_data(
        api_client.supplement_dispute(
            dispute_id, program["franchisee_headers"], {"note": "Cooler log attached."},
        )
    )
    return program


def setup_dispute_after_two_info_cycles(program=None, item_code="FS-1",
                                        requested_points=30, **kwargs) -> dict:
    """A dispute that has completed both permitted information cycles."""
    kwargs.setdefault("with_reviewer", True)
    program = setup_filed_dispute(program, item_code, requested_points, **kwargs)
    dispute_id = program["dispute"]["id"]
    reviewer_headers = program["reviewer_calibration_headers"]
    program["info_requests"] = []
    for index, captured_at in enumerate(("2026-08-05T12:00:00Z", "2026-08-05T12:30:00Z")):
        program["info_requests"].append(
            get_success_data(
                api_client.request_dispute_info(
                    dispute_id,
                    f.request_info_payload(
                        information_requested=f"Supporting document {index + 1}.",
                    ),
                    reviewer_headers,
                )
            )
        )
        attach_dispute_photo(program, dispute_id, captured_at=captured_at)
        program["dispute"] = get_success_data(
            api_client.supplement_dispute(
                dispute_id, program["franchisee_headers"],
                {"note": f"Document {index + 1} attached."},
            )
        )
    return program
