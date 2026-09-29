"""Composite setup helpers.

Every test runs against a freshly started server with an empty database, so
each helper here builds its preconditions from scratch through the public API
only.  Helpers are layered: single-step writers, then state-progression
shortcuts, then whole-hierarchy builders, then accumulation and finalisation
shortcuts.

Two disciplines are baked in because the contract requires them:

* the acting `X-User-ID` of an `AffiliateOperator` is the club's own `id`
  (PRD 2.1), so every operator call threads the affiliate id;
* the three guarded creates each bump their parent's `version` (PRD 2.7), so
  every helper re-reads the parent immediately before the create.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_success

from . import factories
from .api_client import ApiClient
from .constants import ORG_CURRICULUM_VERSION
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    FARM_DIRECTOR_HEADERS,
    INTERNATIONAL_SCOUT_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    make_affiliate_operator_headers,
)


# ---------------------------------------------------------------------------
# Tier 1 — single-step writers and readers
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the logical clock (PRD 2.5).  Available to all five roles."""
    response = api.set_clock(to_iso8601, headers or COMPLIANCE_OFFICER_HEADERS)
    return validate_success(response, 200)


def create_affiliate(api: ApiClient, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
    response = api.create_affiliate(
        factories.affiliate_payload(**overrides), headers or FARM_DIRECTOR_HEADERS
    )
    return validate_success(response, 201)


def read_affiliate(api: ApiClient, affiliate_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_affiliate(affiliate_id, headers or FARM_DIRECTOR_HEADERS), 200)


def affiliate_version(api: ApiClient, affiliate_id: str) -> int:
    return read_affiliate(api, affiliate_id)["version"]


def create_agreement(api: ApiClient, affiliate_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
    response = api.create_agreement(
        affiliate_id,
        factories.agreement_payload(**overrides),
        headers or COMPLIANCE_OFFICER_HEADERS,
    )
    return validate_success(response, 201)


def dispose_agreement(api: ApiClient, agreement_id: str, action: str, headers: Optional[Dict[str, str]] = None, **fields: Any) -> Dict[str, Any]:
    response = api.dispose_agreement(
        agreement_id,
        factories.disposition_payload(action, **fields),
        headers or COMPLIANCE_OFFICER_HEADERS,
    )
    return validate_success(response, 200)


def submit_agreement(api: ApiClient, agreement_id: str, affiliate_id: str) -> Dict[str, Any]:
    """`SUBMIT` is `AffiliateOperator`-only and scoped to the club (PRD 2.1)."""
    return dispose_agreement(
        api, agreement_id, "SUBMIT", make_affiliate_operator_headers(affiliate_id)
    )


def activate_agreement(api: ApiClient, agreement_id: str) -> Dict[str, Any]:
    return dispose_agreement(api, agreement_id, "ACTIVATE")


def create_player(api: ApiClient, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
    response = api.create_player(
        factories.player_payload(**overrides), headers or FARM_DIRECTOR_HEADERS
    )
    return validate_success(response, 201)


def read_player(api: ApiClient, player_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_player(player_id, headers or FARM_DIRECTOR_HEADERS), 200)


def player_version(api: ApiClient, player_id: str) -> int:
    return read_player(api, player_id)["version"]


def request_clearance(api: ApiClient, player_id: str, clearance_type: str = "LEVEL_ASSIGNMENT", headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    response = api.create_medical_clearance(
        player_id,
        factories.medical_clearance_payload(clearance_type=clearance_type),
        headers or FARM_DIRECTOR_HEADERS,
    )
    return validate_success(response, 201)


def dispose_clearance(api: ApiClient, clearance_id: str, action: str, **fields: Any) -> Dict[str, Any]:
    response = api.dispose_medical_clearance(
        clearance_id, factories.disposition_payload(action, **fields), MEDICAL_DIRECTOR_HEADERS
    )
    return validate_success(response, 200)


def issue_clearance(
    api: ApiClient,
    player_id: str,
    clearance_type: str = "LEVEL_ASSIGNMENT",
    cleared_workload_ceiling_index: Any = 25.00,
    expires_on: str = "2026-12-31",
) -> Dict[str, Any]:
    """Request and then ISSUE a clearance of the given type."""
    clearance = request_clearance(api, player_id, clearance_type)
    return dispose_clearance(
        api,
        clearance["id"],
        "ISSUE",
        cleared_workload_ceiling_index=cleared_workload_ceiling_index,
        expires_on=expires_on,
    )


def create_assignment(api: ApiClient, player_id: str, affiliate_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create an assignment, re-reading the player's `version` first (PRD 2.7)."""
    expected = overrides.pop("expected_player_version", None)
    if expected is None:
        expected = player_version(api, player_id)
    response = api.create_assignment(
        factories.assignment_payload(player_id, affiliate_id, expected, **overrides),
        FARM_DIRECTOR_HEADERS,
    )
    return validate_success(response, 201)


def read_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return validate_success(api.get_assignment(assignment_id, FARM_DIRECTOR_HEADERS), 200)


def dispose_assignment(api: ApiClient, assignment_id: str, action: str, **fields: Any) -> Dict[str, Any]:
    response = api.dispose_assignment(
        assignment_id, factories.disposition_payload(action, **fields), FARM_DIRECTOR_HEADERS
    )
    return validate_success(response, 200)


def create_plan(api: ApiClient, assignment_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api.create_development_plan(
        assignment_id, factories.development_plan_payload(**overrides), FARM_DIRECTOR_HEADERS
    )
    return validate_success(response, 201)


def dispose_plan(api: ApiClient, plan_id: str, action: str, headers: Optional[Dict[str, str]] = None, **fields: Any) -> Dict[str, Any]:
    response = api.dispose_development_plan(
        plan_id, factories.disposition_payload(action, **fields), headers or FARM_DIRECTOR_HEADERS
    )
    return validate_success(response, 200)


def log_outing(api: ApiClient, assignment_id: str, log_date: str, headers: Optional[Dict[str, str]] = None, **measures: Any) -> Dict[str, Any]:
    response = api.create_workload_log(
        assignment_id,
        factories.workload_log_payload(log_date=log_date, **measures),
        headers or FARM_DIRECTOR_HEADERS,
    )
    return validate_success(response, 201)


def create_staff_member(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_staff_member(
        factories.staff_member_payload(**overrides), FARM_DIRECTOR_HEADERS
    )
    return validate_success(response, 201)


def create_allocation(api: ApiClient, staff_member_id: str, affiliate_id: str, **overrides: Any) -> Dict[str, Any]:
    """Propose an allocation, re-reading the affiliate's `version` first (PRD 2.7)."""
    expected = overrides.pop("expected_affiliate_version", None)
    if expected is None:
        expected = affiliate_version(api, affiliate_id)
    response = api.create_staff_allocation(
        factories.staff_allocation_payload(staff_member_id, affiliate_id, expected, **overrides),
        FARM_DIRECTOR_HEADERS,
    )
    return validate_success(response, 201)


def dispose_allocation(api: ApiClient, allocation_id: str, action: str, **fields: Any) -> Dict[str, Any]:
    response = api.dispose_staff_allocation(
        allocation_id, factories.disposition_payload(action, **fields), FARM_DIRECTOR_HEADERS
    )
    return validate_success(response, 200)


def file_facility_review(api: ApiClient, affiliate_id: str, category: str, review_date: str, score: int) -> Dict[str, Any]:
    response = api.create_facility_review(
        affiliate_id,
        factories.facility_review_payload(category=category, review_date=review_date, score=score),
        COMPLIANCE_OFFICER_HEADERS,
    )
    return validate_success(response, 201)


def dispose_facility_review(api: ApiClient, review_id: str, action: str, headers: Optional[Dict[str, str]] = None, **fields: Any) -> Dict[str, Any]:
    response = api.dispose_facility_review(
        review_id, factories.disposition_payload(action, **fields), headers or COMPLIANCE_OFFICER_HEADERS
    )
    return validate_success(response, 200)


def create_pool(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_signing_pool(
        factories.signing_pool_payload(**overrides), COMPLIANCE_OFFICER_HEADERS
    )
    return validate_success(response, 201)


def read_pool(api: ApiClient, pool_id: str) -> Dict[str, Any]:
    return validate_success(api.get_signing_pool(pool_id, COMPLIANCE_OFFICER_HEADERS), 200)


def pool_version(api: ApiClient, pool_id: str) -> int:
    return read_pool(api, pool_id)["version"]


def create_signing(api: ApiClient, pool_id: str, player_id: str, academy_affiliate_id: str, **overrides: Any) -> Dict[str, Any]:
    """Submit a signing, re-reading the pool's `version` first (PRD 2.7)."""
    expected = overrides.pop("expected_pool_version", None)
    if expected is None:
        expected = pool_version(api, pool_id)
    response = api.create_international_signing(
        factories.international_signing_payload(
            pool_id, player_id, academy_affiliate_id, expected, **overrides
        ),
        INTERNATIONAL_SCOUT_HEADERS,
    )
    return validate_success(response, 201)


def dispose_signing(api: ApiClient, signing_id: str, action: str, **fields: Any) -> Dict[str, Any]:
    response = api.dispose_international_signing(
        signing_id, factories.disposition_payload(action, **fields), COMPLIANCE_OFFICER_HEADERS
    )
    return validate_success(response, 200)


def dispose_report(api: ApiClient, report_id: str, action: str, headers: Optional[Dict[str, str]] = None, **fields: Any) -> Dict[str, Any]:
    response = api.dispose_transaction_report(
        report_id, factories.disposition_payload(action, **fields), headers or COMPLIANCE_OFFICER_HEADERS
    )
    return validate_success(response, 200)


def list_rows(response) -> List[Dict[str, Any]]:
    """Return the `data` array of a list response."""
    body = response.json()
    assert response.status_code == 200, f"expected 200 from a list endpoint, got {response.status_code}: {body}"
    return body["data"]


def reports_for(api: ApiClient, assignment_id: str, **params: Any) -> List[Dict[str, Any]]:
    return list_rows(api.list_transaction_reports(assignment_id, COMPLIANCE_OFFICER_HEADERS, params or None))


def option_years_for(api: ApiClient, assignment_id: str, **params: Any) -> List[Dict[str, Any]]:
    return list_rows(api.list_option_years(assignment_id, FARM_DIRECTOR_HEADERS, params or None))


def plans_for(api: ApiClient, assignment_id: str, **params: Any) -> List[Dict[str, Any]]:
    return list_rows(api.list_development_plans(assignment_id, FARM_DIRECTOR_HEADERS, params or None))


def clearances_for(api: ApiClient, player_id: str, **params: Any) -> List[Dict[str, Any]]:
    return list_rows(api.list_medical_clearances(player_id, FARM_DIRECTOR_HEADERS, params or None))


def agreements_for(api: ApiClient, affiliate_id: str, **params: Any) -> List[Dict[str, Any]]:
    return list_rows(api.list_agreements(affiliate_id, COMPLIANCE_OFFICER_HEADERS, params or None))


def reviews_for(api: ApiClient, affiliate_id: str, **params: Any) -> List[Dict[str, Any]]:
    return list_rows(api.list_facility_reviews(affiliate_id, COMPLIANCE_OFFICER_HEADERS, params or None))


def read_agreement(api: ApiClient, affiliate_id: str, agreement_id: str) -> Dict[str, Any]:
    """Read one agreement back through the club's agreement listing."""
    for row in agreements_for(api, affiliate_id):
        if row["id"] == agreement_id:
            return row
    raise AssertionError(f"agreement {agreement_id} not listed under affiliate {affiliate_id}")


def read_review(api: ApiClient, affiliate_id: str, review_id: str) -> Dict[str, Any]:
    for row in reviews_for(api, affiliate_id):
        if row["id"] == review_id:
            return row
    raise AssertionError(f"facility review {review_id} not listed under affiliate {affiliate_id}")


def read_plan(api: ApiClient, assignment_id: str, plan_id: str) -> Dict[str, Any]:
    for row in plans_for(api, assignment_id):
        if row["id"] == plan_id:
            return row
    raise AssertionError(f"development plan {plan_id} not listed under assignment {assignment_id}")


def read_clearance(api: ApiClient, player_id: str, clearance_id: str) -> Dict[str, Any]:
    for row in clearances_for(api, player_id):
        if row["id"] == clearance_id:
            return row
    raise AssertionError(f"clearance {clearance_id} not listed under player {player_id}")


def read_allocation(api: ApiClient, affiliate_id: str, allocation_id: str) -> Dict[str, Any]:
    for row in list_rows(api.list_affiliate_staff_allocations(affiliate_id, FARM_DIRECTOR_HEADERS)):
        if row["id"] == allocation_id:
            return row
    raise AssertionError(f"allocation {allocation_id} not listed under affiliate {affiliate_id}")


def read_signing(api: ApiClient, signing_id: str) -> Dict[str, Any]:
    return validate_success(api.get_international_signing(signing_id, COMPLIANCE_OFFICER_HEADERS), 200)


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchies
# ---------------------------------------------------------------------------


def licensed_affiliate(
    api: ApiClient,
    affiliate_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    creator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """A club whose licence has been driven DRAFT -> SUBMITTED -> ACTIVE.

    With `minimum_active_players` 0 and no `required_staff_roles`, the posture
    lands on `OPEN` (PRD 2.9), which is the baseline every child write needs.
    """
    affiliate = create_affiliate(api, creator_headers, **(affiliate_overrides or {}))
    agreement = create_agreement(api, affiliate["id"], **(agreement_overrides or {}))
    submit_agreement(api, agreement["id"], affiliate["id"])
    activated = activate_agreement(api, agreement["id"])
    return {
        "affiliate": read_affiliate(api, affiliate["id"]),
        "affiliate_id": affiliate["id"],
        "agreement": activated,
        "agreement_id": agreement["id"],
        "operator_headers": make_affiliate_operator_headers(affiliate["id"]),
    }


def licensed_academy(
    api: ApiClient,
    affiliate_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A `DOMINICAN_ACADEMY` club with an `ACTIVE` licence, for signings."""
    overrides = {"level": "DOMINICAN_ACADEMY", "market_city": "San Pedro de Macoris"}
    overrides.update(affiliate_overrides or {})
    return licensed_affiliate(
        api,
        affiliate_overrides=overrides,
        agreement_overrides=agreement_overrides,
        creator_headers=COMPLIANCE_OFFICER_HEADERS,
    )


def cleared_player(
    api: ApiClient,
    clearance_type: str = "LEVEL_ASSIGNMENT",
    cleared_workload_ceiling_index: Any = 25.00,
    expires_on: str = "2026-12-31",
    creator_headers: Optional[Dict[str, str]] = None,
    **player_overrides: Any,
) -> Dict[str, Any]:
    """A registered player holding one `ISSUED` clearance of the given type."""
    player = create_player(api, creator_headers, **player_overrides)
    clearance = issue_clearance(
        api,
        player["id"],
        clearance_type=clearance_type,
        cleared_workload_ceiling_index=cleared_workload_ceiling_index,
        expires_on=expires_on,
    )
    return {
        "player": read_player(api, player["id"]),
        "player_id": player["id"],
        "clearance": clearance,
        "clearance_id": clearance["id"],
    }


def pending_assignment(
    api: ApiClient,
    affiliate_id: str,
    player_id: Optional[str] = None,
    player_overrides: Optional[Dict[str, Any]] = None,
    clearance_type: str = "LEVEL_ASSIGNMENT",
    **assignment_overrides: Any,
) -> Dict[str, Any]:
    """A cleared player holding one assignment still in `PENDING_CLEARANCE`."""
    bundle: Dict[str, Any] = {}
    if player_id is None:
        bundle = cleared_player(
            api, clearance_type=clearance_type, **(player_overrides or {})
        )
        player_id = bundle["player_id"]
    assignment = create_assignment(api, player_id, affiliate_id, **assignment_overrides)
    bundle.update(
        {
            "player_id": player_id,
            "assignment": assignment,
            "assignment_id": assignment["id"],
        }
    )
    return bundle


# ---------------------------------------------------------------------------
# Tier 3 — full-lifecycle shortcuts
# ---------------------------------------------------------------------------


def active_assignment(
    api: ApiClient,
    affiliate_id: str,
    player_id: Optional[str] = None,
    player_overrides: Optional[Dict[str, Any]] = None,
    clearance_type: str = "LEVEL_ASSIGNMENT",
    **assignment_overrides: Any,
) -> Dict[str, Any]:
    """A cleared player on an assignment already driven to `ACTIVE`."""
    bundle = pending_assignment(
        api,
        affiliate_id,
        player_id=player_id,
        player_overrides=player_overrides,
        clearance_type=clearance_type,
        **assignment_overrides,
    )
    activated = dispose_assignment(api, bundle["assignment_id"], "ACTIVATE")
    bundle["assignment"] = activated
    bundle["player"] = read_player(api, bundle["player_id"])
    return bundle


def licensed_affiliate_with_active_player(
    api: ApiClient,
    affiliate_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    player_overrides: Optional[Dict[str, Any]] = None,
    **assignment_overrides: Any,
) -> Dict[str, Any]:
    """A licensed club carrying exactly one `ACTIVE` level assignment."""
    club = licensed_affiliate(api, affiliate_overrides, agreement_overrides)
    bundle = active_assignment(
        api,
        club["affiliate_id"],
        player_overrides=player_overrides,
        **assignment_overrides,
    )
    club.update(bundle)
    club["affiliate"] = read_affiliate(api, club["affiliate_id"])
    return club


def active_plan_on(api: ApiClient, assignment_id: str, **plan_overrides: Any) -> Dict[str, Any]:
    """A development plan on the assignment, driven `DRAFT` -> `ACTIVE`."""
    plan = create_plan(api, assignment_id, **plan_overrides)
    activated = dispose_plan(api, plan["id"], "ACTIVATE")
    return {"plan": activated, "plan_id": plan["id"]}


def active_allocation_on(
    api: ApiClient,
    affiliate_id: str,
    staff_member_id: Optional[str] = None,
    staff_overrides: Optional[Dict[str, Any]] = None,
    **allocation_overrides: Any,
) -> Dict[str, Any]:
    """A staff allocation at the club driven `PROPOSED` -> `ACTIVE`."""
    if staff_member_id is None:
        member = create_staff_member(api, **(staff_overrides or {}))
        staff_member_id = member["id"]
    allocation = create_allocation(api, staff_member_id, affiliate_id, **allocation_overrides)
    activated = dispose_allocation(api, allocation["id"], "ACTIVATE")
    return {
        "staff_member_id": staff_member_id,
        "allocation": activated,
        "allocation_id": allocation["id"],
    }


def frozen_affiliate(
    api: ApiClient,
    review_category: str = "MEDICAL_ROOM",
    review_date: str = "2026-04-01",
    review_score: int = 60,
    affiliate_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A licensed club driven to `DEFICIENT` facility standing, hence `FROZEN`.

    A `MAJOR` finding lifts `open_major_deficiency_count` to 1, which makes
    `facility_status` `DEFICIENT` and the licence posture `FROZEN` (PRD 2.9).
    """
    club = licensed_affiliate(api, affiliate_overrides, agreement_overrides)
    review = file_facility_review(
        api, club["affiliate_id"], review_category, review_date, review_score
    )
    club["review"] = review
    club["review_id"] = review["id"]
    club["affiliate"] = read_affiliate(api, club["affiliate_id"])
    club["agreement"] = read_agreement(api, club["affiliate_id"], club["agreement_id"])
    return club


def restricted_affiliate(
    api: ApiClient,
    minimum_active_players: int = 1,
    affiliate_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A licensed club whose posture is `RESTRICTED` on the staffing floor.

    With `active_roster_count` 0 below a `minimum_active_players` floor of 1,
    the posture derivation lands on `RESTRICTED` (PRD 2.9).
    """
    overrides = {"minimum_active_players": minimum_active_players}
    overrides.update(agreement_overrides or {})
    return licensed_affiliate(api, affiliate_overrides, overrides)


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------


def log_outings(api: ApiClient, assignment_id: str, outings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Append a sequence of workload outings to one assignment."""
    written = []
    for outing in outings:
        measures = dict(outing)
        log_date = measures.pop("log_date")
        written.append(log_outing(api, assignment_id, log_date, **measures))
    return written


def plan_with_progress(
    api: ApiClient,
    assignment_id: str,
    completed_module_count: int,
    curriculum_modules: Optional[List[str]] = None,
    **plan_overrides: Any,
) -> Dict[str, Any]:
    """An `ACTIVE` plan carrying a recorded module count."""
    bundle = active_plan_on(
        api,
        assignment_id,
        curriculum_modules=curriculum_modules,
        **plan_overrides,
    )
    if completed_module_count > 0:
        bundle["plan"] = dispose_plan(
            api,
            bundle["plan_id"],
            "RECORD_PROGRESS",
            completed_module_count=completed_module_count,
        )
    return bundle


def roster_filled_to(
    api: ApiClient,
    affiliate_id: str,
    count: int,
    effective_date: str = "2026-08-05",
    end_date: str = "2026-09-30",
) -> List[Dict[str, Any]]:
    """Drive the club's `active_roster_count` up to `count` active assignments."""
    bundles = []
    for _ in range(count):
        bundles.append(
            active_assignment(
                api,
                affiliate_id,
                effective_date=effective_date,
                end_date=end_date,
            )
        )
    return bundles


def pool_with_submitted_signing(
    api: ApiClient,
    academy_affiliate_id: str,
    bonus_cents: int = 500000,
    pool_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A pool plus one `INTERNATIONAL_FA` player with a `SUBMITTED` signing."""
    pool = create_pool(api, **(pool_overrides or {}))
    player = create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    signing = create_signing(
        api, pool["id"], player["id"], academy_affiliate_id, bonus_cents=bonus_cents
    )
    return {
        "pool": read_pool(api, pool["id"]),
        "pool_id": pool["id"],
        "player_id": player["id"],
        "signing": signing,
        "signing_id": signing["id"],
    }


# ---------------------------------------------------------------------------
# Tier 5 — finalisation and terminal states
# ---------------------------------------------------------------------------


def pending_report_for(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    """The single `PENDING` transaction report an activation produced."""
    pending = [r for r in reports_for(api, assignment_id) if r["status"] == "PENDING"]
    assert len(pending) == 1, (
        f"expected exactly one PENDING report on assignment {assignment_id}, got {pending}"
    )
    return pending[0]


def settled_agreement(
    api: ApiClient,
    affiliate_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    **audited: Any,
) -> Dict[str, Any]:
    """A licensed club whose agreement has been `SETTLE`d exactly once."""
    club = licensed_affiliate(api, affiliate_overrides, agreement_overrides)
    club["agreement"] = dispose_agreement(api, club["agreement_id"], "SETTLE", **audited)
    return club


def terminated_agreement(
    api: ApiClient,
    affiliate_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A licensed club whose agreement has reached the terminal `TERMINATED`."""
    club = licensed_affiliate(api, affiliate_overrides, agreement_overrides)
    club["agreement"] = dispose_agreement(api, club["agreement_id"], "TERMINATE")
    return club


ORG_CURRICULUM = ORG_CURRICULUM_VERSION
