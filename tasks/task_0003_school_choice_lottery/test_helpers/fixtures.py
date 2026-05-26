"""Composite setup helpers for multi-step preconditions.

Each test in test_suite starts against an empty database (per-test-server
isolation). Every fixture here builds preconditions from scratch using only
PRD-declared endpoints. The server clock is pinned at the start of every
fixture so window-open / window-close / lottery-run / offer-expiry timing
behaves deterministically (PRD §2.9).

Fixtures use `get_success_data` (lenient validator) internally so a setup
failure surfaces as a clear "Setup failed" message rather than a confusing
in-test assertion error.
"""
from typing import List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_ISO,
    DEFAULT_OPENS_AT,
    DEFAULT_CLOSES_AT,
    DEFAULT_LOTTERY_RUNS_AT,
    DEFAULT_CYCLE_LABEL,
)
from .factories import (
    create_district_payload,
    create_school_payload,
    create_boundary_rule_payload,
    create_window_payload,
    create_family_payload,
    create_student_payload,
    create_sibling_bond_payload,
    create_application_payload,
    run_lottery_payload,
    accept_offer_payload,
)
from .test_users import TEST_USERS, make_guardian_headers, make_anonymous_headers


# ---------------------------------------------------------------------
# Clock helpers (PRD §2.9)
# ---------------------------------------------------------------------

def set_clock(iso8601: str = DEFAULT_CLOCK_ISO) -> dict:
    """Pin the server clock to the given ISO 8601 UTC instant."""
    res = api_client.set_clock(iso8601, TEST_USERS["district_admin_headers"])
    if not (200 <= res.status_code < 300):
        raise AssertionError(
            f"Setup failed: could not set clock to {iso8601}: "
            f"HTTP {res.status_code}: {res.text}"
        )
    return res.json().get("data", {})


# ---------------------------------------------------------------------
# Single-call wrappers (return parsed entity dict)
# ---------------------------------------------------------------------

def create_district(**overrides) -> dict:
    return get_success_data(
        api_client.create_district(
            create_district_payload(**overrides),
            TEST_USERS["district_admin_headers"],
        )
    )


def archive_district(district_id: str) -> dict:
    return get_success_data(
        api_client.update_district(
            district_id,
            {"status": "ARCHIVED"},
            TEST_USERS["district_admin_headers"],
        )
    )


def create_school(district_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_school(
            create_school_payload(district_id, **overrides),
            TEST_USERS["district_admin_headers"],
        )
    )


def create_boundary_rule(school_id: str, zone_code: str, is_in_boundary: bool = True) -> dict:
    return get_success_data(
        api_client.create_boundary_rule(
            create_boundary_rule_payload(school_id, zone_code, is_in_boundary=is_in_boundary),
            TEST_USERS["district_admin_headers"],
        )
    )


def create_window(district_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_window(
            create_window_payload(district_id, **overrides),
            TEST_USERS["district_admin_headers"],
        )
    )


def open_window(window_id: str) -> dict:
    return get_success_data(
        api_client.open_window(window_id, TEST_USERS["district_admin_headers"])
    )


def close_window(window_id: str) -> dict:
    return get_success_data(
        api_client.close_window(window_id, TEST_USERS["district_admin_headers"])
    )


def get_window(window_id: str) -> dict:
    return get_success_data(
        api_client.get_window(window_id, TEST_USERS["district_admin_headers"])
    )


def run_lottery_with_current_version(window_id: str) -> dict:
    """Read the window's current version, then run the lottery with it."""
    w = get_window(window_id)
    return get_success_data(
        api_client.run_lottery(
            window_id,
            run_lottery_payload(w["version"]),
            TEST_USERS["district_admin_headers"],
        )
    )


def finalize_window(window_id: str) -> dict:
    return get_success_data(
        api_client.finalize_window(window_id, TEST_USERS["district_admin_headers"])
    )


def expire_offers(window_id: str) -> dict:
    return get_success_data(
        api_client.expire_offers(window_id, TEST_USERS["district_admin_headers"])
    )


def register_family(district_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.register_family(
            create_family_payload(district_id, **overrides),
            make_anonymous_headers(),
        )
    )


def create_student(family_id: str, as_guardian: bool = True, **overrides) -> dict:
    headers = (
        make_guardian_headers(family_id)
        if as_guardian
        else TEST_USERS["district_admin_headers"]
    )
    return get_success_data(
        api_client.create_student(
            create_student_payload(family_id, **overrides), headers
        )
    )


def create_sibling_bond(family_id: str, student_id: str, sibling_student_id: str,
                        school_id: str) -> dict:
    return get_success_data(
        api_client.create_sibling_bond(
            create_sibling_bond_payload(student_id, sibling_student_id, school_id),
            make_guardian_headers(family_id),
        )
    )


def create_application(family_id: str, window_id: str, student_id: str,
                       school_id: str, choice_rank: int = 1) -> dict:
    return get_success_data(
        api_client.create_application(
            create_application_payload(window_id, student_id, school_id, choice_rank),
            make_guardian_headers(family_id),
        )
    )


def submit_application(family_id: str, application_id: str) -> dict:
    return get_success_data(
        api_client.submit_application(
            application_id, make_guardian_headers(family_id)
        )
    )


def withdraw_application(family_id: str, application_id: str) -> dict:
    return get_success_data(
        api_client.withdraw_application(
            application_id, make_guardian_headers(family_id)
        )
    )


def reject_application(application_id: str) -> dict:
    return get_success_data(
        api_client.reject_application(
            application_id, TEST_USERS["district_admin_headers"]
        )
    )


def get_application(application_id: str) -> dict:
    return get_success_data(
        api_client.get_application(
            application_id, TEST_USERS["district_admin_headers"]
        )
    )


def list_offers_for_application(application_id: str, family_id: Optional[str] = None,
                                source: Optional[str] = None) -> List[dict]:
    headers = (
        make_guardian_headers(family_id)
        if family_id is not None
        else TEST_USERS["district_admin_headers"]
    )
    params = {"application_id": application_id}
    if source is not None:
        params["source"] = source
    res = api_client.list_offers(headers, params=params)
    body = res.json()
    return body.get("data", [])


def get_offer(offer_id: str, family_id: Optional[str] = None) -> dict:
    headers = (
        make_guardian_headers(family_id)
        if family_id is not None
        else TEST_USERS["district_admin_headers"]
    )
    return get_success_data(api_client.get_offer(offer_id, headers))


def accept_offer_with_current_version(family_id: str, offer_id: str) -> dict:
    """Read the offer's current version, then accept with it."""
    off = get_offer(offer_id, family_id=family_id)
    return get_success_data(
        api_client.accept_offer(
            offer_id,
            accept_offer_payload(off["version"]),
            make_guardian_headers(family_id),
        )
    )


def decline_offer(family_id: str, offer_id: str) -> dict:
    return get_success_data(
        api_client.decline_offer(offer_id, make_guardian_headers(family_id))
    )


def list_waitlist_entries_for_application(application_id: str) -> List[dict]:
    res = api_client.list_waitlist_entries(
        TEST_USERS["district_admin_headers"],
        params={"application_id": application_id},
    )
    return res.json().get("data", [])


def list_waitlist_entries_for_school(school_id: str, status: Optional[str] = None) -> List[dict]:
    params = {"school_id": school_id}
    if status is not None:
        params["status"] = status
    res = api_client.list_waitlist_entries(
        TEST_USERS["district_admin_headers"], params=params
    )
    return res.json().get("data", [])


# ---------------------------------------------------------------------
# Composite scenario builders
# ---------------------------------------------------------------------

def setup_district_school_window(
    district_overrides: Optional[dict] = None,
    school_overrides: Optional[dict] = None,
    window_overrides: Optional[dict] = None,
    pin_clock_to: str = DEFAULT_CLOCK_ISO,
) -> Tuple[dict, dict, dict]:
    """Minimal DRAFT preconditions: clock pinned, district + school + window
    created. Window left in DRAFT (caller decides when to open/close/run).

    Returns (district, school, window).
    """
    set_clock(pin_clock_to)
    district = create_district(**(district_overrides or {}))
    school = create_school(district["id"], **(school_overrides or {}))
    window = create_window(district["id"], **(window_overrides or {}))
    return district, school, window


def setup_open_window(
    district_overrides: Optional[dict] = None,
    school_overrides: Optional[dict] = None,
    window_overrides: Optional[dict] = None,
    clock_at_open: str = "2026-01-03T00:00:00Z",
) -> Tuple[dict, dict, dict]:
    """District + school + window opened.

    Returns (district, school, window-after-open).
    """
    district, school, window = setup_district_school_window(
        district_overrides=district_overrides,
        school_overrides=school_overrides,
        window_overrides=window_overrides,
    )
    set_clock(clock_at_open)
    window = open_window(window["id"])
    return district, school, window


def setup_family_with_student(
    district_id: str,
    family_overrides: Optional[dict] = None,
    student_overrides: Optional[dict] = None,
) -> Tuple[dict, dict]:
    """Register a family (Anonymous) and add one student (as Guardian)."""
    family = register_family(district_id, **(family_overrides or {}))
    student = create_student(family["id"], **(student_overrides or {}))
    return family, student


def setup_submitted_application(
    family_overrides: Optional[dict] = None,
    student_overrides: Optional[dict] = None,
    school_overrides: Optional[dict] = None,
    district_overrides: Optional[dict] = None,
    window_overrides: Optional[dict] = None,
    choice_rank: int = 1,
) -> dict:
    """Open window + one family + one student + one SUBMITTED application.

    Returns a dict with keys: district, school, window, family, student, application.
    """
    district, school, window = setup_open_window(
        district_overrides=district_overrides,
        school_overrides=school_overrides,
        window_overrides=window_overrides,
    )
    family, student = setup_family_with_student(
        district["id"],
        family_overrides=family_overrides,
        student_overrides=student_overrides,
    )
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=choice_rank)
    app = submit_application(family["id"], app["id"])
    return {
        "district": district,
        "school": school,
        "window": window,
        "family": family,
        "student": student,
        "application": app,
    }


def advance_window_to_closed(window_id: str,
                             clock_at_close: str = DEFAULT_CLOSES_AT) -> dict:
    """Advance clock to closes_at and call close. Returns updated window."""
    set_clock(clock_at_close)
    return close_window(window_id)


def advance_window_to_lottery_run(
    window_id: str,
    clock_at_close: str = DEFAULT_CLOSES_AT,
    clock_at_run: str = DEFAULT_LOTTERY_RUNS_AT,
) -> dict:
    """Close window, advance clock to lottery_runs_at, run lottery with the
    window's current version (OCC). Returns post-run window snapshot."""
    advance_window_to_closed(window_id, clock_at_close=clock_at_close)
    set_clock(clock_at_run)
    return run_lottery_with_current_version(window_id)


def setup_lottery_run_single_app(
    school_overrides: Optional[dict] = None,
    family_overrides: Optional[dict] = None,
    student_overrides: Optional[dict] = None,
    district_overrides: Optional[dict] = None,
    window_overrides: Optional[dict] = None,
    boundary_zone: Optional[str] = None,
) -> dict:
    """Full pipeline through lottery run with a single application.

    With sane defaults (total_seats >= 1, no sibling bond, no boundary rule
    unless `boundary_zone` is passed), the single application will be ACCEPTED
    and one Offer issued. Returns dict with district, school, window, family,
    student, application, offer.
    """
    bundle = setup_submitted_application(
        district_overrides=district_overrides,
        school_overrides=school_overrides,
        window_overrides=window_overrides,
        family_overrides=family_overrides,
        student_overrides=student_overrides,
    )
    if boundary_zone is not None:
        create_boundary_rule(bundle["school"]["id"], boundary_zone, is_in_boundary=True)
    advance_window_to_lottery_run(bundle["window"]["id"])
    bundle["application"] = get_application(bundle["application"]["id"])
    offers = list_offers_for_application(
        bundle["application"]["id"], family_id=bundle["family"]["id"]
    )
    bundle["offer"] = offers[0] if offers else None
    return bundle


def setup_two_app_lottery_one_seat(
    district_overrides: Optional[dict] = None,
    window_overrides: Optional[dict] = None,
    high_poverty_flag: bool = True,
) -> dict:
    """School with total_seats=1, two SUBMITTED applications; lottery runs.

    Family A has `poverty_flag=high_poverty_flag` (boost 0.200 if True);
    Family B has poverty_flag=False. With both other terms zero, A's weight
    beats B's weight when high_poverty_flag=True, so A wins seat and B is
    waitlisted.

    Returns dict with district, school, window, family_a, family_b, student_a,
    student_b, app_a, app_b, offer_a, waitlist_entry_b.
    """
    district, school, window = setup_open_window(
        district_overrides=district_overrides,
        school_overrides={"total_seats": 1},
        window_overrides=window_overrides,
    )
    fam_a, stu_a = setup_family_with_student(
        district["id"],
        family_overrides={"poverty_flag": high_poverty_flag},
        student_overrides={"grade_for_cycle": 4},
    )
    fam_b, stu_b = setup_family_with_student(
        district["id"],
        family_overrides={"poverty_flag": False},
        student_overrides={"grade_for_cycle": 4},
    )
    app_a = create_application(fam_a["id"], window["id"], stu_a["id"],
                               school["id"], choice_rank=1)
    submit_application(fam_a["id"], app_a["id"])
    app_b = create_application(fam_b["id"], window["id"], stu_b["id"],
                               school["id"], choice_rank=1)
    submit_application(fam_b["id"], app_b["id"])
    advance_window_to_lottery_run(window["id"])
    app_a = get_application(app_a["id"])
    app_b = get_application(app_b["id"])
    offers_a = list_offers_for_application(app_a["id"], family_id=fam_a["id"])
    wl_b = list_waitlist_entries_for_application(app_b["id"])
    return {
        "district": district,
        "school": school,
        "window": window,
        "family_a": fam_a, "family_b": fam_b,
        "student_a": stu_a, "student_b": stu_b,
        "app_a": app_a, "app_b": app_b,
        "offer_a": offers_a[0] if offers_a else None,
        "waitlist_entry_b": wl_b[0] if wl_b else None,
    }
