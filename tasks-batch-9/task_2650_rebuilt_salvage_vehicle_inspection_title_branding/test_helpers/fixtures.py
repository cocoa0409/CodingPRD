"""Composite setup helpers for the rebuilt-salvage program.

The server is restarted with an empty store before every test, so every helper
here builds its preconditions from scratch using only the program's own
endpoints. Setup calls use the lenient success reader so a broken precondition
surfaces as a setup failure rather than as a confusing assertion failure.

The two entity-backed roles are threaded by identity: after a rebuilder or an
inspector row exists, every ownership-gated call in these helpers presents that
row's own id as `X-User-ID`.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_EPOCH,
    PHOTO_VIEW_CODES,
    REQUIRED_PART_CLASSES,
    TEST_DEFAULTS,
)
from .factories import (
    cancel_inspection_payload,
    checkpoint_results,
    complete_inspection_payload,
    create_appeal_payload,
    create_application_payload,
    create_damage_report_payload,
    create_deposit_payload,
    create_finding_payload,
    create_fraud_referral_payload,
    create_inspection_station_payload,
    create_inspector_payload,
    create_license_action_payload,
    create_parts_document_payload,
    create_photograph_payload,
    create_rebuilder_payload,
    create_recognition_request_payload,
    create_title_record_payload,
    create_title_transfer_payload,
    create_vehicle_payload,
    decide_appeal_payload,
    decide_recognition_request_payload,
    docs_review_payload,
    investigate_referral_payload,
    issue_rebuilt_title_payload,
    reject_parts_document_payload,
    resolve_referral_payload,
    review_appeal_payload,
    schedule_inspection_payload,
    set_clock_payload,
    start_inspection_payload,
    submit_application_payload,
    surrender_title_payload,
    verify_parts_document_payload,
    withdraw_application_payload,
)
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_rebuilder_headers,
)

api = api_client

ADMIN = TEST_USERS["program_admin_headers"]
CLERK = TEST_USERS["state_title_clerk_headers"]
ADJUSTER = TEST_USERS["insurer_adjuster_headers"]
HEARING_OFFICER = TEST_USERS["hearing_officer_headers"]
FRAUD_INVESTIGATOR = TEST_USERS["fraud_investigator_headers"]

DEFAULT_PART_AMOUNTS = {
    "STRUCTURAL": TEST_DEFAULTS["STRUCTURAL_AMOUNT_CENTS"],
    "RESTRAINT": TEST_DEFAULTS["RESTRAINT_AMOUNT_CENTS"],
    "LIGHTING": TEST_DEFAULTS["LIGHTING_AMOUNT_CENTS"],
}


# ===========================================================================
# clock
# ===========================================================================
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock to an explicit instant."""
    return get_success_data(api.set_clock(set_clock_payload(to_iso8601), ADMIN))


def reset_clock() -> dict:
    """Return the logical clock to the instant it reads before any caller moves it."""
    return set_clock(CLOCK_EPOCH)


advance_clock = set_clock


# ===========================================================================
# registry
# ===========================================================================
def register_vehicle(**overrides) -> dict:
    return get_success_data(api.create_vehicle(create_vehicle_payload(**overrides), CLERK))


def license_rebuilder(**overrides) -> dict:
    return get_success_data(api.create_rebuilder(create_rebuilder_payload(**overrides), ADMIN))


def fund_rebuilder(rebuilder_id: str, amount_cents: int = None) -> dict:
    amount = TEST_DEFAULTS["DEPOSIT_CENTS"] if amount_cents is None else amount_cents
    return get_success_data(
        api.create_deposit(rebuilder_id, create_deposit_payload(amount_cents=amount), ADMIN)
    )


def take_license_action(
    rebuilder_id: str, action: str, headers: Optional[Dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.create_license_action(
            rebuilder_id,
            create_license_action_payload(action, **overrides),
            headers or ADMIN,
        )
    )


def commission_inspector(**overrides) -> dict:
    return get_success_data(api.create_inspector(create_inspector_payload(**overrides), ADMIN))


def open_station(**overrides) -> dict:
    return get_success_data(
        api.create_inspection_station(create_inspection_station_payload(**overrides), ADMIN)
    )


# ===========================================================================
# damage evaluation and titling
# ===========================================================================
def file_damage_report(vehicle_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_damage_report(create_damage_report_payload(vehicle_id, **overrides), ADJUSTER)
    )


def issue_title(vehicle_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_title_record(create_title_record_payload(vehicle_id, **overrides), CLERK)
    )


def issue_salvage_title(vehicle_id: str, source_damage_report_id: str, **overrides) -> dict:
    """A title minted from a total-loss evaluation carries that evaluation's brand."""
    return issue_title(
        vehicle_id, source_damage_report_id=source_damage_report_id, **overrides
    )


def surrender_title(title_id: str, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.surrender_title_record(
            title_id, surrender_title_payload(**overrides), headers or CLERK
        )
    )


def record_conveyance(from_title_id: str, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.create_title_transfer(
            create_title_transfer_payload(from_title_id, **overrides), headers or CLERK
        )
    )


def submit_recognition_request(
    title_record_id: str, expected_title_version: int, headers: Optional[Dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.create_recognition_request(
            create_recognition_request_payload(
                title_record_id, expected_title_version, **overrides
            ),
            headers or CLERK,
        )
    )


def decide_recognition_request(
    request_id: str, mapped_brand_code: str = "REBUILT", headers: Optional[Dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.decide_recognition_request(
            request_id,
            decide_recognition_request_payload(mapped_brand_code, **overrides),
            headers or ADMIN,
        )
    )


# ===========================================================================
# applications and the parts record
# ===========================================================================
def open_application(
    vehicle_id: str, rebuilder_id: str, salvage_title_id: str, **overrides
) -> dict:
    return get_success_data(
        api.create_application(
            create_application_payload(vehicle_id, rebuilder_id, salvage_title_id, **overrides),
            make_rebuilder_headers(rebuilder_id),
        )
    )


def file_parts_document(application_id: str, rebuilder_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_parts_document(
            application_id,
            create_parts_document_payload(**overrides),
            make_rebuilder_headers(rebuilder_id),
        )
    )


def file_photograph(application_id: str, rebuilder_id: str, photo_view_code: str) -> dict:
    return get_success_data(
        api.create_parts_document(
            application_id,
            create_photograph_payload(photo_view_code),
            make_rebuilder_headers(rebuilder_id),
        )
    )


def file_photo_set(
    application_id: str, rebuilder_id: str, views: tuple = PHOTO_VIEW_CODES
) -> List[dict]:
    """File one photograph per distinct view code."""
    return [file_photograph(application_id, rebuilder_id, view) for view in views]


def verify_parts_document(document_id: str, inspector_id: str, **overrides) -> dict:
    return get_success_data(
        api.verify_parts_document(
            document_id,
            verify_parts_document_payload(**overrides),
            make_inspector_headers(inspector_id),
        )
    )


def reject_parts_document(
    document_id: str, inspector_id: str, rejection_reason: str = "ILLEGIBLE", **overrides
) -> dict:
    return get_success_data(
        api.reject_parts_document(
            document_id,
            reject_parts_document_payload(rejection_reason, **overrides),
            make_inspector_headers(inspector_id),
        )
    )


def submit_application(application_id: str, rebuilder_id: str, **overrides) -> dict:
    return get_success_data(
        api.submit_application(
            application_id,
            submit_application_payload(**overrides),
            make_rebuilder_headers(rebuilder_id),
        )
    )


def withdraw_application(application_id: str, rebuilder_id: str, **overrides) -> dict:
    return get_success_data(
        api.withdraw_application(
            application_id,
            withdraw_application_payload(**overrides),
            make_rebuilder_headers(rebuilder_id),
        )
    )


def review_documentation(
    application_id: str, decision: str, headers: Optional[Dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.review_application_docs(
            application_id, docs_review_payload(decision, **overrides), headers or CLERK
        )
    )


def open_and_accept_documentation(
    application_id: str, headers: Optional[Dict] = None
) -> dict:
    """Open the documentation package and then accept it, returning the accepted
    application so its version can be pinned by the scheduling call."""
    review_documentation(application_id, "OPEN", headers)
    return review_documentation(application_id, "ACCEPT", headers)


def issue_rebuilt_title(application_id: str, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.issue_rebuilt_title(
            application_id, issue_rebuilt_title_payload(**overrides), headers or CLERK
        )
    )


# ===========================================================================
# inspection attempts
# ===========================================================================
def schedule_inspection(
    application_id: str,
    inspector_id: str,
    station_id: str,
    expected_application_version: int,
    scheduled_start_at: str = None,
    scheduled_end_at: str = None,
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.schedule_inspection(
            application_id,
            schedule_inspection_payload(
                inspector_id,
                station_id,
                expected_application_version,
                scheduled_start_at,
                scheduled_end_at,
                **overrides,
            ),
            headers or CLERK,
        )
    )


def start_inspection(inspection_id: str, inspector_id: str, **overrides) -> dict:
    return get_success_data(
        api.start_inspection(
            inspection_id,
            start_inspection_payload(**overrides),
            make_inspector_headers(inspector_id),
        )
    )


def record_finding(inspection_id: str, inspector_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_finding(
            inspection_id,
            create_finding_payload(**overrides),
            make_inspector_headers(inspector_id),
        )
    )


def complete_inspection(
    inspection_id: str, inspector_id: str, vin_plate_reading: str, results: list = None, **overrides
) -> dict:
    return get_success_data(
        api.complete_inspection(
            inspection_id,
            complete_inspection_payload(vin_plate_reading, results, **overrides),
            make_inspector_headers(inspector_id),
        )
    )


def cancel_inspection(inspection_id: str, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.cancel_inspection(
            inspection_id, cancel_inspection_payload(**overrides), headers or CLERK
        )
    )


# ===========================================================================
# appeals
# ===========================================================================
def file_appeal(inspection_id: str, rebuilder_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_appeal(
            create_appeal_payload(inspection_id, **overrides),
            make_rebuilder_headers(rebuilder_id),
        )
    )


def review_appeal(appeal_id: str, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.review_appeal(appeal_id, review_appeal_payload(**overrides), headers or HEARING_OFFICER)
    )


def decide_appeal(
    appeal_id: str, decision: str = "DENY", headers: Optional[Dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.decide_appeal(
            appeal_id, decide_appeal_payload(decision, **overrides), headers or HEARING_OFFICER
        )
    )


# ===========================================================================
# fraud referrals
# ===========================================================================
def open_fraud_referral(vehicle_id: str, headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api.create_fraud_referral(
            create_fraud_referral_payload(vehicle_id, **overrides), headers or CLERK
        )
    )


def investigate_fraud_referral(
    referral_id: str, headers: Optional[Dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.investigate_fraud_referral(
            referral_id, investigate_referral_payload(**overrides), headers or FRAUD_INVESTIGATOR
        )
    )


def resolve_fraud_referral(
    referral_id: str,
    outcome: str = "SUBSTANTIATED",
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.resolve_fraud_referral(
            referral_id,
            resolve_referral_payload(outcome, **overrides),
            headers or FRAUD_INVESTIGATOR,
        )
    )


# ===========================================================================
# reads
# ===========================================================================
def read_vehicle(vehicle_id: str) -> dict:
    return get_success_data(api.get_vehicle(vehicle_id, ADMIN))


def read_rebuilder(rebuilder_id: str) -> dict:
    return get_success_data(api.get_rebuilder(rebuilder_id, ADMIN))


def read_inspector(inspector_id: str) -> dict:
    return get_success_data(api.get_inspector(inspector_id, ADMIN))


def read_station(station_id: str) -> dict:
    return get_success_data(api.get_inspection_station(station_id, ADMIN))


def read_damage_report(report_id: str) -> dict:
    return get_success_data(api.get_damage_report(report_id, ADMIN))


def read_title(title_id: str) -> dict:
    return get_success_data(api.get_title_record(title_id, ADMIN))


def read_application(application_id: str) -> dict:
    return get_success_data(api.get_application(application_id, ADMIN))


def read_fee_quote(application_id: str) -> dict:
    return get_success_data(api.get_fee_quote(application_id, ADMIN))


def read_parts_document(document_id: str) -> dict:
    return get_success_data(api.get_parts_document(document_id, ADMIN))


def read_inspection(inspection_id: str) -> dict:
    return get_success_data(api.get_inspection(inspection_id, ADMIN))


def read_finding(finding_id: str) -> dict:
    return get_success_data(api.get_finding(finding_id, ADMIN))


def read_appeal(appeal_id: str) -> dict:
    return get_success_data(api.get_appeal(appeal_id, ADMIN))


def read_fraud_referral(referral_id: str) -> dict:
    return get_success_data(api.get_fraud_referral(referral_id, ADMIN))


def read_recognition_request(request_id: str) -> dict:
    return get_success_data(api.get_recognition_request(request_id, ADMIN))


def read_conveyance(transfer_id: str) -> dict:
    return get_success_data(api.get_title_transfer(transfer_id, ADMIN))


# ===========================================================================
# Tier 1 — program actors and a branded vehicle
# ===========================================================================
def setup_program_actors(
    deposit_cents: Optional[int] = None,
    rebuilder_overrides: Optional[Dict] = None,
    inspector_overrides: Optional[Dict] = None,
    station_overrides: Optional[Dict] = None,
    with_station: bool = True,
) -> dict:
    """A licensed rebuilder (funded unless `deposit_cents` is 0), a commissioned
    inspector and, by default, an open inspection station.

    Returns a dict with `rebuilder`, `inspector`, `station`, plus the identity
    headers each of the two entity-backed actors must present.
    """
    rebuilder = license_rebuilder(**(rebuilder_overrides or {}))
    if deposit_cents != 0:
        rebuilder = fund_rebuilder(rebuilder["id"], deposit_cents)
    inspector = commission_inspector(**(inspector_overrides or {}))
    station = open_station(**(station_overrides or {})) if with_station else None
    return {
        "rebuilder": rebuilder,
        "rebuilder_id": rebuilder["id"],
        "rebuilder_headers": make_rebuilder_headers(rebuilder["id"]),
        "inspector": inspector,
        "inspector_id": inspector["id"],
        "inspector_headers": make_inspector_headers(inspector["id"]),
        "station": station,
        "station_id": station["id"] if station else None,
    }


def setup_salvage_titled_vehicle(
    body_class: str = "SEDAN",
    acv_cents: Optional[int] = None,
    repair_estimate_cents: Optional[int] = None,
    vehicle_overrides: Optional[Dict] = None,
    report_overrides: Optional[Dict] = None,
    title_overrides: Optional[Dict] = None,
) -> dict:
    """A registered vehicle, a filed total-loss evaluation and the branded title
    the evaluation triggers.

    Returns a dict with `vehicle`, `damage_report` and `salvage_title`.
    """
    vehicle_payload = {"body_class": body_class}
    if body_class == "TRAILER":
        vehicle_payload.update({"make": "Wells", "model": "Cargo", "model_year": 2020})
    elif body_class == "MOTORCYCLE":
        vehicle_payload.update({"make": "Kawa", "model": "Vulcan", "model_year": 2020})
    vehicle_payload.update(vehicle_overrides or {})
    vehicle = register_vehicle(**vehicle_payload)

    report_payload = {}
    if acv_cents is not None:
        report_payload["acv_cents"] = acv_cents
    if repair_estimate_cents is not None:
        report_payload["repair_estimate_cents"] = repair_estimate_cents
    if body_class in ("TRAILER", "MOTORCYCLE"):
        report_payload.setdefault("acv_cents", 400_000)
        report_payload.setdefault("repair_estimate_cents", 320_000)
        report_payload.setdefault("odometer_reading_miles", 0)
    report_payload.update(report_overrides or {})
    damage_report = file_damage_report(vehicle["id"], **report_payload)

    salvage_title = issue_salvage_title(
        vehicle["id"], damage_report["id"], **(title_overrides or {})
    )
    return {
        "vehicle": vehicle,
        "vehicle_id": vehicle["id"],
        "vin": vehicle["vin"],
        "damage_report": damage_report,
        "damage_report_id": damage_report["id"],
        "salvage_title": salvage_title,
        "salvage_title_id": salvage_title["id"],
    }


def default_parts_document_specs(body_class: str = "SEDAN") -> List[dict]:
    """One receipt per part class the body classification requires."""
    specs = []
    for part_class in REQUIRED_PART_CLASSES.get(body_class, []):
        specs.append(
            {
                "part_class": part_class,
                "doc_type": "RECEIPT",
                "source_type": "NEW",
                "amount_cents": DEFAULT_PART_AMOUNTS.get(part_class, 10_000),
            }
        )
    return specs


# ===========================================================================
# Tier 2 — an application in DRAFT, with and without its parts record
# ===========================================================================
def setup_draft_application(
    body_class: str = "SEDAN",
    deposit_cents: Optional[int] = None,
    declared_repair_cost_cents: Optional[int] = None,
    expedite_requested: bool = False,
    actors: Optional[Dict] = None,
    vehicle_env: Optional[Dict] = None,
    rebuilder_overrides: Optional[Dict] = None,
    inspector_overrides: Optional[Dict] = None,
    station_overrides: Optional[Dict] = None,
    vehicle_overrides: Optional[Dict] = None,
    report_overrides: Optional[Dict] = None,
    **application_overrides,
) -> dict:
    """Actors + a salvage-branded vehicle + an application in DRAFT.

    Returns a single environment dict carrying every id the later stages need.
    """
    env = dict(
        actors
        or setup_program_actors(
            deposit_cents=deposit_cents,
            rebuilder_overrides=rebuilder_overrides,
            inspector_overrides=inspector_overrides,
            station_overrides=station_overrides,
        )
    )
    env.update(
        vehicle_env
        or setup_salvage_titled_vehicle(
            body_class=body_class,
            vehicle_overrides=vehicle_overrides,
            report_overrides=report_overrides,
        )
    )
    env["body_class"] = body_class
    if declared_repair_cost_cents is None:
        declared_repair_cost_cents = env["damage_report"]["repair_estimate_cents"]
    application = open_application(
        env["vehicle_id"],
        env["rebuilder_id"],
        env["salvage_title_id"],
        declared_repair_cost_cents=declared_repair_cost_cents,
        expedite_requested=expedite_requested,
        **application_overrides,
    )
    env["application"] = application
    env["application_id"] = application["id"]
    env["documents"] = {}
    env["document_list"] = []
    env["photos"] = []
    return env


def add_parts_documents(
    env: dict, specs: Optional[List[dict]] = None, verify: bool = True
) -> dict:
    """File the given parts documents on the application in `env`, verifying each
    one unless its spec says otherwise.

    Each spec is a parts-document payload; the optional key `verify` overrides the
    call-wide default for that one document.
    """
    if specs is None:
        specs = default_parts_document_specs(env.get("body_class", "SEDAN"))
    for spec in specs:
        spec = dict(spec)
        should_verify = spec.pop("verify", verify)
        document = file_parts_document(env["application_id"], env["rebuilder_id"], **spec)
        if should_verify:
            document = verify_parts_document(document["id"], env["inspector_id"])
        env["documents"][spec.get("part_class", document["part_class"])] = document
        env["document_list"].append(document)
    env["application"] = read_application(env["application_id"])
    return env


def add_photo_set(env: dict, views: tuple = PHOTO_VIEW_CODES) -> dict:
    """File one photograph per required view on the application in `env`."""
    env["photos"] = file_photo_set(env["application_id"], env["rebuilder_id"], views)
    env["application"] = read_application(env["application_id"])
    return env


def setup_submission_ready_application(
    body_class: str = "SEDAN",
    specs: Optional[List[dict]] = None,
    views: tuple = PHOTO_VIEW_CODES,
    **kwargs,
) -> dict:
    """An application in DRAFT whose documentation is complete: every required
    part class verified and the full photograph set on file."""
    env = setup_draft_application(body_class=body_class, **kwargs)
    add_parts_documents(env, specs)
    add_photo_set(env, views)
    return env


# ===========================================================================
# Tier 3 — a submitted application and an accepted documentation package
# ===========================================================================
def setup_submitted_application(body_class: str = "SEDAN", **kwargs) -> dict:
    """A complete documentation package carried through submission, so the
    application sits in SUBMITTED with its assessed fee escrowed."""
    env = setup_submission_ready_application(body_class=body_class, **kwargs)
    env["application"] = submit_application(env["application_id"], env["rebuilder_id"])
    env["app_version"] = env["application"]["version"]
    return env


def setup_docs_accepted_application(body_class: str = "SEDAN", **kwargs) -> dict:
    """A submitted application whose documentation package has been opened and
    accepted, leaving it ready for scheduling."""
    env = setup_submitted_application(body_class=body_class, **kwargs)
    env["application"] = open_and_accept_documentation(env["application_id"])
    env["app_version"] = env["application"]["version"]
    return env


# ===========================================================================
# Tier 4 — an inspection attempt, scheduled then under way
# ===========================================================================
def setup_scheduled_inspection(
    body_class: str = "SEDAN",
    scheduled_start_at: Optional[str] = None,
    scheduled_end_at: Optional[str] = None,
    env: Optional[Dict] = None,
    **kwargs,
) -> dict:
    """An accepted application with one inspection booked into an inspector's
    calendar and a station's bay."""
    env = dict(env or setup_docs_accepted_application(body_class=body_class, **kwargs))
    inspection = schedule_inspection(
        env["application_id"],
        env["inspector_id"],
        env["station_id"],
        env["app_version"],
        scheduled_start_at,
        scheduled_end_at,
    )
    env["inspection"] = inspection
    env["inspection_id"] = inspection["id"]
    env["application"] = read_application(env["application_id"])
    env["app_version"] = env["application"]["version"]
    return env


def setup_inspection_in_progress(
    body_class: str = "SEDAN",
    scheduled_start_at: Optional[str] = None,
    scheduled_end_at: Optional[str] = None,
    env: Optional[Dict] = None,
    **kwargs,
) -> dict:
    """A booked inspection that the assigned inspector has started, with the
    program clock standing at the slot's start instant."""
    env = setup_scheduled_inspection(
        body_class=body_class,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        env=env,
        **kwargs,
    )
    set_clock(env["inspection"]["scheduled_start_at"])
    env["inspection"] = start_inspection(env["inspection_id"], env["inspector_id"])
    env["application"] = read_application(env["application_id"])
    env["app_version"] = env["application"]["version"]
    return env


# ===========================================================================
# Tier 5 — a decided inspection and the title it produces
# ===========================================================================
def setup_completed_inspection(
    results: Optional[List[dict]] = None,
    vin_plate_reading: Optional[str] = None,
    body_class: str = "SEDAN",
    env: Optional[Dict] = None,
    **kwargs,
) -> dict:
    """An inspection carried to completion with the given checkpoint outcomes.

    `vin_plate_reading` defaults to the vehicle's own identification number, so the
    identity check reads as verified unless a test deliberately passes a mismatch.
    """
    env = setup_inspection_in_progress(body_class=body_class, env=env, **kwargs)
    env["inspection"] = complete_inspection(
        env["inspection_id"],
        env["inspector_id"],
        vin_plate_reading or env["vin"],
        results,
    )
    env["application"] = read_application(env["application_id"])
    env["app_version"] = env["application"]["version"]
    return env


def setup_passed_application(body_class: str = "SEDAN", env: Optional[Dict] = None, **kwargs) -> dict:
    """An application whose inspection scored every checkpoint clean, leaving it
    in PASSED and awaiting title issuance."""
    return setup_completed_inspection(
        results=checkpoint_results(), body_class=body_class, env=env, **kwargs
    )


def setup_failed_application(body_class: str = "SEDAN", env: Optional[Dict] = None, **kwargs) -> dict:
    """An application whose inspection fell short of the adequacy threshold,
    leaving it in FAILED with one attempt consumed."""
    return setup_completed_inspection(
        results=checkpoint_results(
            structural_frame="FAIL",
            restraint_system="FAIL",
            vin_integrity="PASS",
            suspension_steering="FAIL",
            lamps_glazing="FAIL",
        ),
        body_class=body_class,
        env=env,
        **kwargs,
    )


def setup_rebuilt_title_issued(body_class: str = "SEDAN", env: Optional[Dict] = None, **kwargs) -> dict:
    """A passed application carried through to an issued rebuilt title.

    Adds `rebuilt_title` to the environment and refreshes the superseded salvage row.
    """
    env = setup_passed_application(body_class=body_class, env=env, **kwargs)
    rebuilt_title = issue_rebuilt_title(env["application_id"])
    env["rebuilt_title"] = rebuilt_title
    env["rebuilt_title_id"] = rebuilt_title["id"]
    env["salvage_title"] = read_title(env["salvage_title_id"])
    env["application"] = read_application(env["application_id"])
    env["app_version"] = env["application"]["version"]
    return env


def setup_appealable_failure(body_class: str = "SEDAN", env: Optional[Dict] = None, **kwargs) -> dict:
    """A failed inspection with the rebuilder's appeal already on file."""
    env = setup_failed_application(body_class=body_class, env=env, **kwargs)
    appeal = file_appeal(env["inspection_id"], env["rebuilder_id"])
    env["appeal"] = appeal
    env["appeal_id"] = appeal["id"]
    env["application"] = read_application(env["application_id"])
    env["app_version"] = env["application"]["version"]
    return env
