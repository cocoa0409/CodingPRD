"""Composite setup helpers for the HEDIS quality-measure pipeline.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before each test, so nothing carries over).
Setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup step failed" error naming the failing step.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    FULL_YEAR_2025,
    create_abstraction_payload,
    create_batch_payload,
    create_engagement_payload,
    create_enrollment_segment_payload,
    create_member_payload,
    create_overread_payload,
    create_provider_payload,
    create_record_payload,
    create_run_payload,
    create_sample_payload,
    create_season_payload,
    create_spec_payload,
)
from .test_users import (
    TEST_USERS,
    make_abstractor_headers,
    make_overreader_headers,
    make_quality_analyst_headers,
)

ADMIN = TEST_USERS["quality_admin_headers"]
ANALYST = TEST_USERS["quality_analyst_headers"]
ABSTRACTOR = TEST_USERS["abstractor_headers"]
OVERREADER = TEST_USERS["overreader_headers"]
RELATIONS = TEST_USERS["provider_relations_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
DIRECTOR = TEST_USERS["quality_director_headers"]


# --- Tier 1: reference data and state progression ---

def set_clock(api, to_iso8601):
    """Advance the server logical clock (PRD §2.5)."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_season(api, **overrides):
    """Create a measurement season (born DRAFT). Returns the season."""
    return get_success_data(api.create_season(create_season_payload(**overrides), ADMIN))


def create_and_open_season(api, **overrides):
    """Create a season and open it. Returns the OPEN season."""
    season = create_season(api, **overrides)
    return get_success_data(api.open_season(season["id"], ADMIN))


def load_spec(api, season_id, **overrides):
    """Load a measure specification into a season.

    Reads the season first so expected_season_version always matches the
    current season version (PRD §2.6). Returns the LOADED spec.
    """
    season = get_success_data(api.get_season(season_id, ADMIN))
    payload = create_spec_payload(season_id, season["version"], **overrides)
    return get_success_data(api.create_spec(payload, ADMIN))


def create_active_spec(api, season_id, **overrides):
    """Load + activate a specification. Returns the ACTIVE spec."""
    spec = load_spec(api, season_id, **overrides)
    return get_success_data(api.activate_spec(spec["id"], ADMIN))


def register_provider(api, provider_ref="P1", **overrides):
    return get_success_data(
        api.create_provider(create_provider_payload(provider_ref, **overrides), ADMIN)
    )


def register_member(api, member_ref, provider_ref=None, **overrides):
    if provider_ref is not None:
        overrides.setdefault("attributed_provider_ref", provider_ref)
    return get_success_data(
        api.create_member(create_member_payload(member_ref, **overrides), ADMIN)
    )


def enroll_member(api, member_id, segments=None):
    """Attach enrollment segments (default: one full-year 2025 segment)."""
    if segments is None:
        segments = [FULL_YEAR_2025]
    rows = []
    for span_start, span_end in segments:
        rows.append(
            get_success_data(
                api.create_enrollment_segment(
                    create_enrollment_segment_payload(
                        member_id, span_start=span_start, span_end=span_end
                    ),
                    ADMIN,
                )
            )
        )
    return rows


def register_enrolled_member(api, member_ref, provider_ref=None, segments=None, **overrides):
    """Member + enrollment segments. Returns the member row."""
    member = register_member(api, member_ref, provider_ref=provider_ref, **overrides)
    enroll_member(api, member["id"], segments)
    return member


def create_run(api, season_id, spec_id, user_id=None):
    headers = make_quality_analyst_headers(user_id) if user_id else ANALYST
    return get_success_data(api.create_run(create_run_payload(season_id, spec_id), headers))


def identify_population(api, run_id, user_id=None):
    headers = make_quality_analyst_headers(user_id) if user_id else ANALYST
    return get_success_data(api.identify_population(run_id, headers))


def compute_rate(api, run_id, user_id=None):
    """Compute the run's rate, reading the current run version first (PRD §2.6)."""
    headers = make_quality_analyst_headers(user_id) if user_id else ANALYST
    run = get_success_data(api.get_run(run_id, ANALYST))
    return get_success_data(
        api.compute_rate(run_id, {"expected_measure_run_version": run["version"]}, headers)
    )


# --- Tier 2: populated/computed/submitted run scenarios ---

def setup_populated_run(api, member_refs=("M1",), spec_overrides=None, season_overrides=None,
                        provider_ref=None, member_attrs=None, analyst_id=None,
                        provider_refs=None):
    """Season OPEN + ACTIVE spec + enrolled members + run POPULATED.

    Returns dict(season, spec, run, members, providers). `member_attrs` maps
    member_ref -> per-member overrides (e.g. birth_date, gender, segments,
    provider_ref). `providers` maps provider_ref -> provider row. `provider_refs`
    registers several providers up front (needed when member_attrs attribute
    members to different providers).
    """
    season = create_and_open_season(api, **(season_overrides or {}))
    spec = create_active_spec(api, season["id"], **(spec_overrides or {}))
    providers = {}
    for ref in provider_refs or ([provider_ref] if provider_ref is not None else []):
        providers[ref] = register_provider(api, ref)
    members = []
    for ref in member_refs:
        attrs = dict((member_attrs or {}).get(ref, {}))
        attr_provider = attrs.pop("provider_ref", provider_ref)
        segments = attrs.pop("segments", None)
        members.append(
            register_enrolled_member(api, ref, provider_ref=attr_provider,
                                     segments=segments, **attrs)
        )
    run = create_run(api, season["id"], spec["id"], user_id=analyst_id)
    run = identify_population(api, run["id"], user_id=analyst_id)
    return {"season": season, "spec": spec, "run": run, "members": members,
            "providers": providers}


def setup_rate_computed_run(api, **kwargs):
    """Populated run advanced to RATE_COMPUTED. Returns the scenario dict."""
    scenario = setup_populated_run(api, **kwargs)
    scenario["run"] = compute_rate(api, scenario["run"]["id"], user_id=kwargs.get("analyst_id"))
    return scenario


def setup_submitted_run(api, analyst_id="qa-1", **kwargs):
    """Run advanced to SUBMITTED. Returns the scenario dict."""
    kwargs["analyst_id"] = analyst_id
    scenario = setup_rate_computed_run(api, **kwargs)
    headers = make_quality_analyst_headers(analyst_id)
    scenario["run"] = get_success_data(api.submit_run(scenario["run"]["id"], headers))
    return scenario


# --- Tier 3: hybrid sampling, chases, abstractions ---

def setup_hybrid_sample(api, member_refs=("M001", "M002"), floor=2, spec_overrides=None,
                        provider_ref="P1", member_attrs=None, season_overrides=None):
    """Populated HYBRID run + drawn sample + its chart chases.

    Returns dict(season, spec, run, sample, chases, members); chases are in the
    list order returned by the sample's chart-chase listing (member_ref ASC per
    PRD §2.3).
    """
    overrides = {"collection_method": "HYBRID", "sample_size_floor": floor}
    overrides.update(spec_overrides or {})
    scenario = setup_populated_run(
        api,
        member_refs=member_refs,
        spec_overrides=overrides,
        season_overrides=season_overrides,
        provider_ref=provider_ref,
        member_attrs=member_attrs,
    )
    sample = get_success_data(
        api.create_sample(create_sample_payload(scenario["run"]["id"]), ANALYST)
    )
    chases, _meta = _list_all(api.list_sample_chases(sample["id"], ANALYST))
    scenario.update({"sample": sample, "chases": chases})
    return scenario


def _list_all(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


def receive_chases(api, chases):
    """Mark every chase RECEIVED. Returns the updated chases in input order."""
    return [get_success_data(api.receive_chase(c["id"], ANALYST)) for c in chases]


def create_submitted_abstraction(api, chase_id, result="HIT", abstractor_id="abs-1"):
    """Create an abstraction on a RECEIVED chase and submit it. Returns the
    SUBMITTED abstraction."""
    headers = make_abstractor_headers(abstractor_id)
    abstraction = get_success_data(
        api.create_abstraction(create_abstraction_payload(chase_id, result), headers)
    )
    return get_success_data(api.submit_abstraction(abstraction["id"], headers))


def record_overread(api, abstraction_id, outcome="AGREE", final_result=None,
                    reviewer_id="orr-1"):
    """Record an over-read review. Returns the OverReadReview row."""
    return get_success_data(
        api.create_overread(
            create_overread_payload(abstraction_id, outcome, final_result),
            make_overreader_headers(reviewer_id),
        )
    )


def setup_hybrid_with_submitted_abstractions(api, member_refs, results, floor=None,
                                             abstractor_id="abs-1", spec_overrides=None,
                                             provider_ref="P1", member_attrs=None,
                                             season_overrides=None):
    """HYBRID sample with every chase RECEIVED and one submitted abstraction per
    chase (results[i] for member_refs[i]). Returns the scenario dict with
    `abstractions` added (aligned with `chases`)."""
    scenario = setup_hybrid_sample(
        api,
        member_refs=member_refs,
        floor=floor if floor is not None else len(member_refs),
        spec_overrides=spec_overrides,
        provider_ref=provider_ref,
        member_attrs=member_attrs,
        season_overrides=season_overrides,
    )
    scenario["chases"] = receive_chases(api, scenario["chases"])
    abstractions = []
    for chase, result in zip(scenario["chases"], results):
        abstractions.append(
            create_submitted_abstraction(api, chase["id"], result, abstractor_id)
        )
    scenario["abstractions"] = abstractions
    return scenario


def setup_finalized_sample(api, member_refs=("M001", "M002"), results=("HIT", "HIT"),
                           floor=None, spec_overrides=None):
    """HYBRID sample walked to FINALIZED: every chase abstracted and submitted,
    every selector-flagged abstraction over-read AGREE, IRR evaluated, finalize.

    Returns the scenario dict. Caller controls member count/results.
    """
    scenario = setup_hybrid_with_submitted_abstractions(
        api, member_refs, results, floor=floor, spec_overrides=spec_overrides
    )
    overread_all_flagged(api, scenario["abstractions"], scenario["sample"]["id"])
    scenario["sample"] = get_success_data(
        api.finalize_sample(scenario["sample"]["id"], ANALYST)
    )
    return scenario


def overread_all_flagged(api, abstractions, sample_id, reviewer_id="orr-1"):
    """Over-read AGREE every selector-flagged SUBMITTED abstraction, re-evaluating
    IRR after each sweep round, until no flagged SUBMITTED abstraction remains.
    Needed because the selector top-up re-flags siblings whenever an abstraction
    leaves SUBMITTED (PRD §3.5)."""
    for _ in range(len(abstractions) + 1):
        pending = []
        for abstraction in abstractions:
            current = get_success_data(api.get_abstraction(abstraction["id"], ANALYST))
            if current["requires_overread"] and current["status"] == "SUBMITTED":
                pending.append(current)
        if not pending:
            break
        for current in pending:
            record_overread(api, current["id"], "AGREE", reviewer_id=reviewer_id)
        get_success_data(api.evaluate_irr(sample_id, ANALYST))


def run_hybrid_pipeline(api, season_id, spec_id, results, records=None,
                        source_type="LAB_FEED", analyst_id="qa-1"):
    """Full hybrid pipeline on an existing season: create run -> identify population
    -> draw sample -> receive chases -> create+submit one abstraction per chase
    (results aligned with the member_ref-ascending chase order) -> over-read every
    selector-flagged abstraction AGREE -> evaluate-irr -> finalize -> optionally
    screen+accept a supplemental batch -> compute-rate.

    Returns dict(run=<computed MeasureRun>, sample, chases, abstractions, batch).
    """
    run = create_run(api, season_id, spec_id, user_id=analyst_id)
    run = identify_population(api, run["id"], user_id=analyst_id)
    sample = get_success_data(api.create_sample(create_sample_payload(run["id"]), ANALYST))
    chases, _meta = _list_all(api.list_sample_chases(sample["id"], ANALYST))
    receive_chases(api, chases)
    abstractions = [
        create_submitted_abstraction(api, chase["id"], result)
        for chase, result in zip(chases, results)
    ]
    overread_all_flagged(api, abstractions, sample["id"])
    sample = get_success_data(api.finalize_sample(sample["id"], ANALYST))
    batch = None
    if records:
        _created, _rows, batch = setup_accepted_batch(api, run["id"], records, source_type)
    computed = compute_rate(api, run["id"], user_id=analyst_id)
    return {
        "run": computed,
        "sample": sample,
        "chases": chases,
        "abstractions": abstractions,
        "batch": batch,
    }


# --- Tier 4: supplemental evidence ---

def setup_batch_with_records(api, run_id, records, source_type="LAB_FEED"):
    """Create a batch and add records. `records` is a list of
    (member_ref, service_date, evidence_code) tuples. Returns (batch, records)."""
    batch = get_success_data(
        api.create_supplemental_batch(create_batch_payload(run_id, source_type), ANALYST)
    )
    rows = [
        get_success_data(
            api.create_supplemental_record(
                create_record_payload(batch["id"], ref, service_date, evidence), ANALYST
            )
        )
        for ref, service_date, evidence in records
    ]
    return batch, rows


def setup_screened_batch(api, run_id, records, source_type="LAB_FEED"):
    """Batch + records, screened. Returns (batch, records, screened_batch)."""
    batch, rows = setup_batch_with_records(api, run_id, records, source_type)
    screened = get_success_data(api.screen_batch(batch["id"], ANALYST))
    return batch, rows, screened


def setup_accepted_batch(api, run_id, records, source_type="LAB_FEED"):
    """Batch + records, screened and accepted. Returns (batch, records, accepted)."""
    batch, rows, _screened = setup_screened_batch(api, run_id, records, source_type)
    accepted = get_success_data(api.accept_batch(batch["id"], ANALYST))
    return batch, rows, accepted


# --- Tier 5: audit / certification path ---

def setup_engagement(api, season_id, run_id, auditor_id="aud-1",
                     window_start="2026-01-01T00:00:00Z", window_end="2026-07-01T00:00:00Z"):
    """Schedule an audit engagement. Returns the SCHEDULED engagement."""
    return get_success_data(
        api.create_engagement(
            create_engagement_payload(
                season_id, run_id, auditor_user_id=auditor_id,
                window_start=window_start, window_end=window_end,
            ),
            AUDITOR,
        )
    )


def setup_run_under_review(api, window_start="2026-01-01T00:00:00Z",
                           window_end="2026-07-01T00:00:00Z", analyst_id="qa-1",
                           auditor_id="aud-1", **kwargs):
    """SUBMITTED run + engagement moved to IN_REVIEW (clock must sit inside the
    engagement window). Returns scenario dict with `engagement` added."""
    scenario = setup_submitted_run(api, analyst_id=analyst_id, **kwargs)
    engagement = setup_engagement(
        api, scenario["season"]["id"], scenario["run"]["id"],
        auditor_id=auditor_id, window_start=window_start, window_end=window_end,
    )
    engagement = get_success_data(api.begin_review(engagement["id"], AUDITOR))
    scenario["engagement"] = engagement
    return scenario


# --- read helpers ---

def get_run(api, run_id):
    return get_success_data(api.get_run(run_id, ANALYST))


def get_season(api, season_id):
    return get_success_data(api.get_season(season_id, ADMIN))


def get_sample(api, sample_id):
    return get_success_data(api.get_sample(sample_id, ANALYST))


def get_chase(api, chase_id):
    return get_success_data(api.get_chase(chase_id, ANALYST))


def get_abstraction(api, abstraction_id):
    return get_success_data(api.get_abstraction(abstraction_id, ANALYST))


def get_provider(api, provider_id):
    return get_success_data(api.get_provider(provider_id, ANALYST))


def list_run_entries(api, run_id, params=None):
    return _list_all(api.list_run_population_entries(run_id, ANALYST, params=params))


def list_run_gaps(api, run_id, params=None):
    return _list_all(api.list_run_gap_items(run_id, ANALYST, params=params))


def list_sample_chases(api, sample_id, params=None):
    return _list_all(api.list_sample_chases(sample_id, ANALYST, params=params))


def list_batch_records(api, batch_id, params=None):
    return _list_all(api.list_batch_records(batch_id, ANALYST, params=params))


def list_engagement_findings(api, engagement_id, params=None):
    return _list_all(api.list_engagement_findings(engagement_id, AUDITOR, params=params))


def list_abstraction_overreads(api, abstraction_id, params=None):
    return _list_all(api.list_abstraction_overreads(abstraction_id, ANALYST, params=params))
