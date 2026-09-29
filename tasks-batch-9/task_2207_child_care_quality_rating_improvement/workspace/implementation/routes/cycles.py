"""Rating cycles, self-assessments, scoring, award and publication (PRD §3.3, §3.5, §3.6)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calculations as calc
import cascades
import lookups
import response
import serializers
import store
import validation as v
from auth import require
from errors import fail
from validation import as_date, body

bp = Blueprint("cycles", __name__)

OPEN_CYCLE_STATES = ("DRAFT", "SELF_ASSESSMENT_SUBMITTED", "DOCS_VERIFIED",
                     "OBSERVATION_SCHEDULED", "OBSERVATION_FINALIZED", "AWARDED",
                     "UNDER_APPEAL")


def self_assessment_of(cycle_id):
    for sa in store.sort_created(list(store.DB.self_assessments.values())):
        if sa["rating_cycle_id"] == cycle_id:
            return sa
    return None


def visits_of(cycle_id):
    return [x for x in store.DB.observation_visits.values()
            if x["rating_cycle_id"] == cycle_id]


def finalized_visit_of(cycle_id):
    finalized = [x for x in visits_of(cycle_id) if x["status"] == "FINALIZED"]
    if finalized:
        return store.sort_created(finalized)[-1]
    live = [x for x in visits_of(cycle_id) if x["status"] != "CANCELLED"]
    return store.sort_created(live)[-1] if live else None


def all_domains_ready():
    domains = list(store.DB.standard_domains.values())
    if len(domains) != 5:
        return False
    total = Decimal("0")
    for domain in domains:
        total += calc.dec(domain["weight"])
    return total == Decimal("1.00")


# ------------------------------------------------------------- rating cycles


@bp.post("/providers/<provider_id>/rating-cycles")
def open_rating_cycle(provider_id):
    principal = require("Provider")
    provider = lookups.get_provider(provider_id)
    lookups.own_provider(principal, provider)
    data = body()
    cycle_type = v.req_enum(data, "cycle_type", v.CYCLE_TYPES)
    expected = v.req_int(data, "expected_provider_version")

    # Gate 1: optimistic concurrency (PRD §2.5).
    if expected != int(provider["version"]):
        fail("ERR_STALE_VERSION", "expected_provider_version does not match the provider version")

    existing_cycles = cascades.cycles_of(provider["id"])
    is_first = len(existing_cycles) == 0

    # Gate 2: the provider's own standing.
    if provider["status"] == "ACTIVE":
        pass
    elif provider["status"] == "ENROLLED" and is_first:
        pass
    else:
        fail("ERR_PROVIDER_STATE_INVALID",
             "the provider may not open a rating cycle in status %s" % provider["status"])

    active_cycle = None
    for cycle in existing_cycles:
        if cycle["status"] == "ACTIVE":
            active_cycle = cycle
            break

    # Gate 3: the re-rating window (REMAND is exempt).
    if cycle_type == "RERATING":
        opens_on = as_date(active_cycle.get("rerating_window_opens_on")) if active_cycle else None
        if opens_on is None or store.today() < opens_on:
            fail("ERR_RERATING_WINDOW_NOT_OPEN", "the re-rating window is not open yet")

    # Gate 4: the single-open-cycle rule.
    for cycle in existing_cycles:
        if cycle["status"] in OPEN_CYCLE_STATES:
            fail("ERR_ACTIVE_CYCLE_EXISTS", "the provider already holds an open rating cycle")

    rec = store.base_record(
        provider_id=provider["id"],
        cycle_type=cycle_type,
        opened_on=store.now(),
        status="DRAFT",
        publication_status="UNPUBLISHED",
        observation_composite=None,
        reliability_pct=None,
        domain_points={},
        block_clearance={},
        highest_block_cleared=None,
        weighted_total=None,
        points_tier=None,
        awarded_tier=None,
        score_variant=None,
        awarded_on=None,
        awarded_by_user_id=None,
        effective_date=None,
        expires_on=None,
        validity_months=None,
        rerating_window_opens_on=None,
        published_at=None,
        published_snapshot=None,
        appeal_adjusted=False,
        supersedes_cycle_id=active_cycle["id"] if active_cycle else None,
        superseded_by_cycle_id=None,
    )
    store.DB.rating_cycles[rec["id"]] = rec
    store.touch(provider)
    return response.created(serializers.dump("rating_cycle", rec))


@bp.get("/rating-cycles")
def list_rating_cycles():
    require("StateAdministrator", "Provider", "AppealReviewer")
    records = store.sort_created(list(store.DB.rating_cycles.values()))
    for field in ("provider_id", "status", "publication_status",
                  "supersedes_cycle_id", "superseded_by_cycle_id"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("rating_cycle"))


@bp.get("/rating-cycles/<rating_cycle_id>")
def read_rating_cycle(rating_cycle_id):
    principal = require("StateAdministrator", "Provider", "AppealReviewer", "Observer")
    cycle = lookups.get_cycle(rating_cycle_id)
    lookups.own_cycle(principal, cycle)
    return response.ok(serializers.dump("rating_cycle", cycle))


@bp.get("/rating-cycles/<rating_cycle_id>/score-preview")
def score_preview(rating_cycle_id):
    principal = require("StateAdministrator", "Provider")
    cycle = lookups.get_cycle(rating_cycle_id)
    lookups.own_cycle(principal, cycle)
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "PROVISIONAL"
    if variant not in v.SCORE_VARIANTS:
        fail("ERR_VALIDATION", "variant must be PROVISIONAL or FINAL")
    provider = store.DB.providers[cycle["provider_id"]]
    sa = self_assessment_of(cycle["id"])
    if variant == "FINAL" and (sa is None or sa["status"] != "VERIFIED"):
        fail("ERR_SELF_ASSESSMENT_NOT_VERIFIED",
             "the final variant requires a VERIFIED self-assessment")
    value, _, _ = calc.compute_credential_compliance(provider)
    shadow_provider = dict(provider)
    shadow_provider["credential_compliance_pct"] = value
    points = calc.compute_domain_points(cycle, variant, shadow_provider, sa)
    determination = calc.compute_tier_determination(cycle, points, variant)
    extra = dict(determination)
    extra["domain_points"] = points
    extra["score_variant"] = variant
    return response.ok(serializers.dump("rating_cycle", cycle, extra))


# ---------------------------------------------------------- self-assessments


@bp.post("/rating-cycles/<rating_cycle_id>/self-assessments")
def submit_self_assessment(rating_cycle_id):
    principal = require("Provider")
    cycle = lookups.get_cycle(rating_cycle_id)
    lookups.own_cycle(principal, cycle)
    data = body()
    domains = calc.domains_by_code()
    claimed = v.req_points_map(data, "claimed_points", domains)
    documentation = v.req_array(data, "documentation", non_empty=True)
    records = []
    for entry in documentation:
        if not isinstance(entry, dict):
            fail("ERR_VALIDATION", "each documentation record must be an object")
        record = {
            "domain_code": v.req_enum(entry, "domain_code", v.DOMAIN_CODES),
            "evidence_type": v.req_enum(entry, "evidence_type", v.EVIDENCE_TYPES),
            "reference_label": v.req_str(entry, "reference_label"),
            "page_count": v.req_int(entry, "page_count", 0),
        }
        records.append(record)

    if self_assessment_of(cycle["id"]) is not None:
        fail("ERR_DUPLICATE_RESOURCE", "this cycle already has a self-assessment")
    if cycle["status"] != "DRAFT":
        fail("ERR_CYCLE_STATE_INVALID", "a self-assessment may be submitted only from DRAFT")
    if not all_domains_ready():
        fail("ERR_VALIDATION",
             "all five standard domains must exist with weights summing to exactly 1.00")

    documented = []
    for record in records:
        if record["domain_code"] not in documented:
            documented.append(record["domain_code"])

    rec = store.base_record(
        rating_cycle_id=cycle["id"],
        claimed_points=claimed,
        documentation=records,
        verified_points=None,
        documented_domains=documented,
        status="SUBMITTED",
        return_count=0,
        verified_on=None,
    )
    store.DB.self_assessments[rec["id"]] = rec
    cycle["status"] = "SELF_ASSESSMENT_SUBMITTED"
    store.touch(cycle)
    return response.created(serializers.dump("self_assessment", rec))


@bp.get("/self-assessments")
def list_self_assessments():
    require("StateAdministrator", "Provider", "AppealReviewer")
    records = store.sort_created(list(store.DB.self_assessments.values()))
    for field in ("rating_cycle_id", "status"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("self_assessment"))


@bp.get("/self-assessments/<self_assessment_id>")
def read_self_assessment(self_assessment_id):
    principal = require("StateAdministrator", "Provider", "AppealReviewer")
    sa = lookups.get_self_assessment(self_assessment_id)
    lookups.own_via_cycle(principal, sa["rating_cycle_id"])
    return response.ok(serializers.dump("self_assessment", sa))


@bp.post("/self-assessments/<self_assessment_id>/verification-decisions")
def verification_decision(self_assessment_id):
    require("StateAdministrator")
    sa = lookups.get_self_assessment(self_assessment_id)
    cycle = lookups.get_cycle(sa["rating_cycle_id"])
    provider = store.DB.providers[cycle["provider_id"]]
    data = body()
    decision = v.req_enum(data, "decision", ["APPROVE", "RETURN"])
    v.opt_str(data, "note")
    domains = calc.domains_by_code()

    if decision == "APPROVE":
        verified = v.req_points_map(data, "verified_points", domains)
        if cycle["status"] != "SELF_ASSESSMENT_SUBMITTED":
            fail("ERR_CYCLE_STATE_INVALID",
                 "verification approval requires the cycle in SELF_ASSESSMENT_SUBMITTED")
        if sa["status"] not in ("SUBMITTED", "RETURNED"):
            fail("ERR_CYCLE_STATE_INVALID",
                 "the self-assessment must be in SUBMITTED or RETURNED")
        documented = sa.get("documented_domains") or []
        for code, points in verified.items():
            if points > 0 and code not in documented:
                fail("ERR_DOCUMENTATION_COVERAGE_GAP",
                     "domain %s has verified points but no documentation" % code)
        sa["verified_points"] = verified
        sa["status"] = "VERIFIED"
        sa["verified_on"] = store.now()
        store.touch(sa)
        cycle["status"] = "DOCS_VERIFIED"
        calc.refresh_credential_compliance(provider)
        store.touch(provider)
        cycle["domain_points"] = calc.compute_domain_points(
            cycle, "PROVISIONAL", provider, sa)
        store.touch(cycle)
    else:
        if cycle["status"] not in ("SELF_ASSESSMENT_SUBMITTED", "DOCS_VERIFIED"):
            fail("ERR_CYCLE_STATE_INVALID",
                 "a return requires the cycle in SELF_ASSESSMENT_SUBMITTED or DOCS_VERIFIED")
        if int(sa["return_count"]) >= 2:
            fail("ERR_SELF_ASSESSMENT_RETURN_LIMIT",
                 "the self-assessment has already been returned twice")
        sa["status"] = "RETURNED"
        sa["return_count"] = int(sa["return_count"]) + 1
        sa["verified_points"] = None
        store.touch(sa)
        if cycle["status"] == "DOCS_VERIFIED":
            cycle["status"] = "SELF_ASSESSMENT_SUBMITTED"
        cycle["domain_points"] = {}
        store.touch(cycle)

    return response.ok(serializers.dump("self_assessment", sa))


# ------------------------------------------------------------------- award


@bp.post("/rating-cycles/<rating_cycle_id>/award")
def award_cycle(rating_cycle_id):
    principal = require("StateAdministrator")
    cycle = lookups.get_cycle(rating_cycle_id)
    provider = store.DB.providers[cycle["provider_id"]]
    data = body()
    score_variant = v.req_enum(data, "score_variant", v.SCORE_VARIANTS)

    if cycle["status"] != "OBSERVATION_FINALIZED":
        fail("ERR_CYCLE_STATE_INVALID", "an award requires the cycle in OBSERVATION_FINALIZED")
    if score_variant != "FINAL":
        fail("ERR_VALIDATION",
             "FINAL is the only score_variant permitted from OBSERVATION_FINALIZED")

    sa = self_assessment_of(cycle["id"])
    calc.refresh_credential_compliance(provider)

    # Check 1: the secondary-observer requirement.
    provisional_points = calc.compute_domain_points(cycle, "PROVISIONAL", provider, sa)
    provisional = calc.compute_tier_determination(cycle, provisional_points, "PROVISIONAL")
    visit = finalized_visit_of(cycle["id"])
    if provisional["awarded_tier"] >= 4 and (visit is None or
                                             not visit.get("secondary_observer_id")):
        fail("ERR_SECONDARY_OBSERVER_REQUIRED",
             "a tier 4 or 5 award requires a reliability-checked observation")

    # Check 2: registry completeness.
    for cred in store.DB.staff_credentials.values():
        if cred["provider_id"] != provider["id"]:
            continue
        if cred["employment_status"] != "ACTIVE":
            continue
        if cred["registry_status"] in ("UNLINKED", "PENDING"):
            fail("ERR_CREDENTIAL_REGISTRY_UNLINKED",
                 "every active staff credential must be resolved against the registry")

    # Check 3: the compliance floor, measured against awarded_tier.
    final_points = calc.compute_domain_points(cycle, "FINAL", provider, sa)
    determination = calc.compute_tier_determination(cycle, final_points, "FINAL")
    floor = calc.TIER_COMPLIANCE_FLOOR[determination["awarded_tier"]]
    if calc.dec(provider["credential_compliance_pct"]) < floor:
        fail("ERR_CREDENTIAL_COMPLIANCE_BELOW_MINIMUM",
             "credential compliance is below the minimum for tier %d"
             % determination["awarded_tier"])

    # Check 4: the self-assessment must be VERIFIED.
    if sa is None or sa["status"] != "VERIFIED":
        fail("ERR_SELF_ASSESSMENT_NOT_VERIFIED", "the self-assessment is not VERIFIED")

    # Check 5: no open appeal of this cycle.
    if cascades.has_open_appeal(cycle["id"]):
        fail("ERR_OPEN_APPEAL_BLOCKS_ACTION", "an appeal of this cycle is still open")

    # Check 6: the block floor.
    if determination["highest_block_cleared"] < 1:
        fail("ERR_BLOCK_GATE_NOT_MET", "block 1 is not cleared, so no rating may be issued")

    award_instant = store.now()
    inherited = cycle.get("effective_date") if cycle.get("appeal_adjusted") else None
    validity = calc.compute_validity(award_instant, determination["awarded_tier"], inherited)

    cycle["domain_points"] = final_points
    cycle["weighted_total"] = determination["weighted_total"]
    cycle["points_tier"] = determination["points_tier"]
    cycle["block_clearance"] = determination["block_clearance"]
    cycle["highest_block_cleared"] = determination["highest_block_cleared"]
    cycle["awarded_tier"] = determination["awarded_tier"]
    cycle["score_variant"] = score_variant
    cycle["awarded_on"] = award_instant
    cycle["awarded_by_user_id"] = principal.user_id
    cycle["effective_date"] = validity["effective_date"]
    cycle["expires_on"] = validity["expires_on"]
    cycle["validity_months"] = validity["validity_months"]
    cycle["rerating_window_opens_on"] = validity["rerating_window_opens_on"]
    cycle["status"] = "AWARDED"
    store.touch(cycle)

    if validity["effective_date"].date() <= store.today():
        cascades.promote_cycle_to_active(cycle)

    return response.ok(serializers.dump("rating_cycle", cycle))


# ---------------------------------------------------------------- publication


@bp.post("/rating-cycles/<rating_cycle_id>/publish")
def publish_cycle(rating_cycle_id):
    require("StateAdministrator")
    cycle = lookups.get_cycle(rating_cycle_id)
    provider = store.DB.providers[cycle["provider_id"]]
    body()

    if cycle.get("awarded_on") is None:
        fail("ERR_CYCLE_STATE_INVALID", "the cycle carries no award to publish")
    award_date = as_date(cycle["awarded_on"])
    if store.today() < award_date + timedelta(days=10):
        fail("ERR_PUBLICATION_QUIET_PERIOD",
             "the family-notice quiet period has not elapsed")
    if cascades.has_open_appeal(cycle["id"]):
        fail("ERR_OPEN_APPEAL_BLOCKS_ACTION", "an appeal of this cycle is still open")

    cycle["publication_status"] = "PUBLISHED"
    cycle["published_at"] = store.now()
    cycle["published_snapshot"] = {
        "tier": cycle.get("awarded_tier"),
        "weighted_total": cycle.get("weighted_total"),
        "domain_points": dict(cycle.get("domain_points") or {}),
        "licensed_capacity": provider["licensed_capacity"],
        "county_code": provider["county_code"],
    }
    store.touch(cycle)
    provider["public_listing_visible"] = True
    store.touch(provider)
    return response.ok(serializers.dump("rating_cycle", cycle))


@bp.get("/public/ratings")
def public_ratings():
    require("FamilyViewer", "Provider", "StateAdministrator")
    records = [c for c in store.sort_created(list(store.DB.rating_cycles.values()))
               if c["publication_status"] == "PUBLISHED"]
    county_code = request.args.get("county_code")
    if county_code:
        records = [c for c in records
                   if (c.get("published_snapshot") or {}).get("county_code") == county_code]
    tier = request.args.get("tier")
    if tier:
        try:
            wanted = int(tier)
        except ValueError:
            fail("ERR_VALIDATION", "tier must be an integer")
        records = [c for c in records if c.get("awarded_tier") == wanted]
    return response.paginate(records, serializers.maker("rating_cycle"))
