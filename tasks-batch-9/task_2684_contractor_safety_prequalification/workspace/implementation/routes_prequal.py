"""Prequalification cycles, safety statistics, submission and grading."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascade
import derive
import response
import serialize
import store
import validators as V
from errors import fail
from store import S, insert, now, touch

bp = Blueprint("prequal", __name__)


def _new_prequal_row(contractor_id, client_id, cycle_year):
    row = store.base_row()
    row.update(
        {
            "contractor_id": contractor_id,
            "client_id": client_id,
            "cycle_year": cycle_year,
            "status": "DRAFT",
            "provisional_composite_score": None,
            "final_composite_score": None,
            "grade": None,
            "deficiency_codes": [],
            "effective_thresholds": None,
            "graded_at": None,
            "graded_by_user_id": None,
            "expires_at": None,
            "conditional_expires_at": None,
            "audit_state": "NOT_SELECTED",
            "audit_selected_at": None,
            "audit_findings_count": 0,
        }
    )
    return row


@bp.route("/prequalifications", methods=["POST"])
def create_prequalification():
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(
        [
            ("contractor_id", "string", True),
            ("client_id", "string", True),
            ("cycle_year", "integer", True),
            ("expected_contractor_version", "integer", True),
        ]
    )
    cycle_year = body["cycle_year"]
    clock_year = now().year
    if cycle_year < clock_year - 1 or cycle_year > clock_year + 1:
        fail("ERR_INVALID_FIELD_VALUE", "cycle_year must be within one year of the clock year.")

    contractor = V.get_contractor(body["contractor_id"])
    client = V.get_client(body["client_id"])
    auth.check_owner(role, user_id, contractor_id=contractor["id"])

    if body["expected_contractor_version"] != contractor["version"]:
        fail("ERR_STALE_VERSION", "expected_contractor_version does not match the contractor.")
    if contractor["status"] != "ACTIVE":
        fail("ERR_CONTRACTOR_NOT_ACTIVE", "The contractor is not ACTIVE.")

    for existing in derive.preqs_of_contractor(contractor["id"]):
        if existing["client_id"] != client["id"]:
            continue
        if existing["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW"):
            fail("ERR_DUPLICATE_PREQUALIFICATION", "An in-flight application already exists.")
        if existing["cycle_year"] == cycle_year and existing["status"] in (
            "APPROVED",
            "CONDITIONAL",
            "SUSPENDED",
        ):
            fail("ERR_DUPLICATE_PREQUALIFICATION", "That cycle year is already settled.")

    row = _new_prequal_row(contractor["id"], client["id"], cycle_year)
    insert(S.prequalifications, row)

    cascade.supersede_older_standings(contractor, client["id"], cycle_year)
    touch(contractor)
    derive.recompute_open_deficiency_count(contractor)
    return response.created(serialize.prequalification(row))


STAT_FIELDS = [
    ("prequalification_id", "string", False),
    ("reporting_year", "integer", True),
    ("hours_worked", "integer", True),
    ("recordable_incidents", "integer", True),
    ("dart_cases", "integer", True),
    ("fatalities", "integer", True),
    ("emr", "number", True),
    ("citation_count_willful", "integer", True),
    ("citation_count_serious", "integer", True),
    ("citation_count_other", "integer", True),
    ("source_document_ref", "string", True),
]


@bp.route("/prequalifications/<prequalification_id>/safety-statistics", methods=["POST"])
def create_safety_statistic(prequalification_id):
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(STAT_FIELDS)
    hours_worked = V.check_int_range("hours_worked", body["hours_worked"], lo=0)
    recordable = V.check_int_range("recordable_incidents", body["recordable_incidents"], lo=0)
    dart_cases = V.check_int_range("dart_cases", body["dart_cases"], lo=0)
    fatalities = V.check_int_range("fatalities", body["fatalities"], lo=0)
    emr = V.check_num_range("emr", body["emr"], lo=0, lo_strict=True)
    willful = V.check_int_range("citation_count_willful", body["citation_count_willful"], lo=0)
    serious = V.check_int_range("citation_count_serious", body["citation_count_serious"], lo=0)
    other = V.check_int_range("citation_count_other", body["citation_count_other"], lo=0)
    source_document_ref = V.check_str_len(
        "source_document_ref", body["source_document_ref"], 1, 120
    )
    reporting_year = body["reporting_year"]

    preq = V.get_prequalification(prequalification_id)
    auth.check_owner(role, user_id, contractor_id=preq["contractor_id"])

    if preq["status"] != "DRAFT":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Statistics may only be filed while the row is DRAFT.")

    if dart_cases > recordable or fatalities > recordable or (recordable > 0 and hours_worked <= 0):
        fail("ERR_STATISTICS_INCONSISTENT", "The reported figures are internally inconsistent.")

    clock_year = now().year
    if reporting_year < clock_year - 3 or reporting_year > clock_year:
        fail("ERR_REPORTING_YEAR_OUT_OF_WINDOW", "reporting_year is outside its four-year window.")

    for existing in derive.stats_of(preq["id"]):
        if existing["reporting_year"] == reporting_year and existing["verification_status"] in (
            "PENDING",
            "VERIFIED",
        ):
            fail("ERR_DUPLICATE_REPORTING_YEAR", "That reporting year is already claimed.")

    row = store.base_row()
    row.update(
        {
            "prequalification_id": preq["id"],
            "reporting_year": reporting_year,
            "hours_worked": hours_worked,
            "recordable_incidents": recordable,
            "dart_cases": dart_cases,
            "fatalities": fatalities,
            "emr": emr,
            "citation_count_willful": willful,
            "citation_count_serious": serious,
            "citation_count_other": other,
            "source_document_ref": source_document_ref,
            "verification_status": "PENDING",
            "verified_by_user_id": None,
            "verified_at": None,
            "trir": calc.incident_rate(recordable, hours_worked),
            "dart_rate": calc.incident_rate(dart_cases, hours_worked),
            "citation_points": calc.citation_points(willful, serious, other),
        }
    )
    insert(S.safety_statistics, row)
    return response.created(serialize.safety_statistic(row))


@bp.route("/safety-statistics/<statistic_id>/verify", methods=["POST"])
def verify_safety_statistic(statistic_id):
    user_id, role = auth.authenticate([auth.ROLE_VERIFICATION_ANALYST])
    body = V.parse_body([("decision", "string", True)])
    decision = V.check_enum("decision", body["decision"], ("VERIFY", "REJECT"))

    row = V.get_leaf(S.safety_statistics, statistic_id)
    if row["verification_status"] != "PENDING":
        fail("ERR_TRANSITION_NOT_ALLOWED", "The statistic has already been decided.")

    row["verification_status"] = "VERIFIED" if decision == "VERIFY" else "REJECTED"
    row["verified_by_user_id"] = user_id
    row["verified_at"] = now()
    touch(row)

    preq = S.prequalifications[row["prequalification_id"]]
    cascade.evaluate_join(preq)
    return response.ok(serialize.safety_statistic(row))


@bp.route("/prequalifications/<prequalification_id>/submit", methods=["POST"])
def submit_prequalification(prequalification_id):
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    V.no_body()
    preq = V.get_prequalification(prequalification_id)
    auth.check_owner(role, user_id, contractor_id=preq["contractor_id"])

    if preq["status"] != "DRAFT":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only a DRAFT prequalification may be submitted.")

    contractor = S.contractors[preq["contractor_id"]]
    if contractor["status"] != "ACTIVE":
        fail("ERR_CONTRACTOR_NOT_ACTIVE", "The contractor is not ACTIVE.")
    if contractor["incident_review_flag"]:
        fail("ERR_INCIDENT_REVIEW_ACTIVE", "The contractor is under active incident review.")

    governing = derive.governing_statistic(preq["id"], ("PENDING", "VERIFIED"))
    if governing is None:
        fail("ERR_STATISTICS_UNVERIFIED", "No governing safety statistic exists.")

    required = calc.required_program_set(contractor["hazard_profile"])
    present = set(p["program_type"] for p in derive.programs_of(preq["id"]))
    if not required.issubset(present):
        fail("ERR_REQUIRED_PROGRAM_MISSING", "A required written program has not been tendered.")

    total, _thresholds, _factor, _tier = derive.score_variant(preq, governing, True)
    preq["status"] = "SUBMITTED"
    preq["provisional_composite_score"] = total
    touch(preq)
    derive.recompute_flow_down(preq["id"])
    cascade.evaluate_join(preq)
    return response.ok(serialize.prequalification(preq))


@bp.route("/prequalifications/<prequalification_id>/grade", methods=["POST"])
def grade_prequalification(prequalification_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    V.no_body()
    preq = V.get_prequalification(prequalification_id)
    auth.check_owner(role, user_id, client_id=preq["client_id"])

    if preq["status"] != "UNDER_REVIEW":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only an UNDER_REVIEW prequalification may be graded.")

    contractor = S.contractors[preq["contractor_id"]]
    client = S.clients[preq["client_id"]]
    if contractor["incident_review_flag"]:
        fail("ERR_INCIDENT_REVIEW_ACTIVE", "The contractor is under active incident review.")

    derive.coverage_gate(contractor, client)

    governing = derive.governing_statistic(preq["id"], ("VERIFIED",))
    if governing is None:
        fail("ERR_STATISTICS_UNVERIFIED", "No verified safety statistic exists.")

    thresholds, factor, tier = derive.resolve_thresholds(preq, False)
    metrics = derive.metrics_from(governing)
    total, _subs = calc.composite_score(metrics, thresholds, derive.weights_of(client))
    letter = calc.grade_band(total, client["grading_policy"])
    outcome, codes = calc.grading_decision(
        metrics, thresholds, client["conditional_band_pct"], letter
    )

    graded_at = now()
    preq["effective_thresholds"] = {
        "max_trir": thresholds["TRIR"],
        "max_dart_rate": thresholds["DART"],
        "max_emr": thresholds["EMR"],
        "max_citation_points": thresholds["CITATION_POINTS"],
        "tightening": factor,
        "hazard_tier": tier,
    }
    preq["final_composite_score"] = total
    preq["grade"] = letter
    preq["graded_at"] = graded_at
    preq["graded_by_user_id"] = user_id
    preq["deficiency_codes"] = codes
    preq["status"] = outcome

    if outcome == "REJECTED":
        preq["expires_at"] = None
        preq["conditional_expires_at"] = None
    else:
        preq["expires_at"] = calc.add_months(
            graded_at, client["requalification_interval_months"]
        )
        if outcome == "CONDITIONAL":
            preq["conditional_expires_at"] = graded_at + timedelta(
                days=calc.CONDITIONAL_CURE_DAYS
            )
        else:
            preq["conditional_expires_at"] = None
    touch(preq)

    if outcome == "REJECTED":
        cascade.revoke_all_granted(preq["id"], "PREQUAL_REJECTED")
    derive.recompute_open_deficiency_count(contractor)
    derive.recompute_flow_down(preq["id"])
    return response.ok(serialize.prequalification(preq))
