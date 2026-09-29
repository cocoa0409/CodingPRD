"""Setup helpers that build preconditions through published endpoints only.

Every helper here drives the real API. Nothing is seeded directly into storage,
because the only contract a test may rely on is the one the PRD publishes. The
helpers are layered: each composite calls the one below it, so a test that needs
an active injection well pays for exactly the chain the PRD requires to reach
one and nothing more.

Each composite returns a context dictionary whose keys are the entities it
created — `project`, `model`, `wellbores`, `tracts`, `plan`, `permit`,
`instrument`, `periods`, `claim` — always holding the freshest payload the
server returned for each.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import (
    CANONICAL_TRACT_SPECS,
    CLOCK_DURING_INJECTION_YEAR,
    DEFAULT_BONUS_PER_ACRE_USD,
    DEFAULT_INJECTION_YEARS,
    DEFAULT_ROYALTY_RATE_PCT,
    MRV_METHODS_SCORE_85,
    PERIOD_1_END,
    PERIOD_1_LEAKAGE_TONNES,
    PERIOD_1_MASS_TONNES,
    PERIOD_1_START,
    PERIOD_2_END,
    PERIOD_2_LEAKAGE_TONNES,
    PERIOD_2_MASS_TONNES,
    PERIOD_2_START,
    STARTUP_CLOCK_UTC,
    TAX_YEAR,
    TRUST_FUND_FACE_AMOUNT_USD,
)
from .factories import (
    accept_offer_payload,
    advance_construction_payload,
    allocate_payload,
    create_financial_instrument_payload,
    create_geologic_model_payload,
    create_injection_well_permit_payload,
    create_legacy_wellbore_payload,
    create_monitoring_method_payload,
    create_monitoring_plan_payload,
    create_pore_space_tract_payload,
    create_remediation_order_payload,
    create_storage_project_payload,
    create_tax_credit_claim_payload,
    lease_offer_payload,
    record_mit_payload,
    report_injection_period_payload,
    run_plume_simulation_payload,
)
from .test_users import TEST_USERS, make_landowner_headers

ADMIN = TEST_USERS["program_admin_headers"]
DEVELOPER = TEST_USERS["project_developer_headers"]
REVIEWER = TEST_USERS["regulatory_reviewer_headers"]
SECOND_REVIEWER = TEST_USERS["second_reviewer_headers"]
VERIFIER = TEST_USERS["independent_verifier_headers"]

CONSTRUCTION_SEQUENCE = [
    "DRILLING",
    "CASING_SET",
    "CEMENT_LOGGED",
    "MIT_PENDING",
    "COMPLETED",
]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_logical_clock(api, to_iso8601=STARTUP_CLOCK_UTC):
    """Move the server-wide logical clock and return the reported instant."""
    response = api.set_current_utc({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------


def open_project(api, **overrides):
    """Create a storage project, which rests at `DRAFT` with `OPEN` posture."""
    response = api.create_storage_project(
        create_storage_project_payload(**overrides), ADMIN
    )
    return get_success_data(response)


def register_geologic_model(api, project_id, expected_project_version, **overrides):
    """Register a model revision against a project at the version just read."""
    response = api.create_geologic_model(
        create_geologic_model_payload(
            project_id, expected_project_version, **overrides
        ),
        DEVELOPER,
    )
    return get_success_data(response)


def simulate_plume(api, model_id, injection_years=DEFAULT_INJECTION_YEARS):
    """Run the plume migration simulation, deriving the rate cap and the radii."""
    response = api.run_plume_simulation(
        model_id, run_plume_simulation_payload(injection_years), DEVELOPER
    )
    return get_success_data(response)


def submit_model(api, model_id, submission_note="initial site characterization"):
    response = api.submit_geologic_model(
        model_id, {"submission_note": submission_note}, DEVELOPER
    )
    return get_success_data(response)


def rule_on_model(
    api,
    model_id,
    decision="ACCEPT",
    review_note="seal integrity acceptable",
    headers=REVIEWER,
):
    response = api.review_geologic_model(
        model_id, {"decision": decision, "review_note": review_note}, headers
    )
    return get_success_data(response)


def finalize_area_of_review(api, model_id):
    """Publish the accepted model's area of review onto the project."""
    response = api.finalize_aor(model_id, {}, DEVELOPER)
    return get_success_data(response)


def register_wellbore(api, project_id, api_number, **overrides):
    """Register a legacy wellbore for area-of-review screening."""
    response = api.create_legacy_wellbore(
        create_legacy_wellbore_payload(project_id, api_number, **overrides), DEVELOPER
    )
    return get_success_data(response)


def register_tract(api, project_id, tract_label, **overrides):
    """Register a pore-space tract, which rests at `lease_status` `UNLEASED`."""
    response = api.create_pore_space_tract(
        create_pore_space_tract_payload(project_id, tract_label, **overrides), DEVELOPER
    )
    return get_success_data(response)


def send_offer(
    api,
    tract,
    bonus_per_acre_usd=DEFAULT_BONUS_PER_ACRE_USD,
    royalty_rate_pct=DEFAULT_ROYALTY_RATE_PCT,
):
    """Send a lease offer guarded on the tract's own version."""
    response = api.send_lease_offer(
        tract["id"],
        lease_offer_payload(
            tract["version"],
            bonus_per_acre_usd=bonus_per_acre_usd,
            royalty_rate_pct=royalty_rate_pct,
        ),
        DEVELOPER,
    )
    return get_success_data(response)


def accept_offer(api, tract, **overrides):
    """Accept the outstanding offer as the landowner entitled to the tract."""
    response = api.respond_to_lease_offer(
        tract["id"],
        accept_offer_payload(**overrides),
        make_landowner_headers(tract["landowner_user_id"]),
    )
    return get_success_data(response)


def execute_tract_lease(
    api,
    tract,
    bonus_per_acre_usd=DEFAULT_BONUS_PER_ACRE_USD,
    royalty_rate_pct=DEFAULT_ROYALTY_RATE_PCT,
):
    """Carry one tract from `UNLEASED` through `OFFER_SENT` to `EXECUTED`."""
    offered = send_offer(
        api,
        tract,
        bonus_per_acre_usd=bonus_per_acre_usd,
        royalty_rate_pct=royalty_rate_pct,
    )
    return accept_offer(api, offered)


def create_monitoring_plan_with_methods(
    api, project_id, methods=None, plan_label="MRV-1"
):
    """Create a plan and add each supplied method to it while it is `DRAFT`."""
    plan = get_success_data(
        api.create_monitoring_plan(
            create_monitoring_plan_payload(project_id, plan_label=plan_label), DEVELOPER
        )
    )
    added = []
    for method in MRV_METHODS_SCORE_85 if methods is None else methods:
        added.append(
            get_success_data(
                api.add_monitoring_method(
                    plan["id"], create_monitoring_method_payload(**method), DEVELOPER
                )
            )
        )
    return plan, added


def submit_plan(api, plan_id, submission_note="monitoring programme for review"):
    response = api.submit_monitoring_plan(
        plan_id, {"submission_note": submission_note}, DEVELOPER
    )
    return get_success_data(response)


def close_both_review_tracks(api, plan_id, headers=REVIEWER):
    """Close the technical-review track and then the public-comment track."""
    get_success_data(
        api.review_monitoring_plan(
            plan_id, {"decision": "COMPLETE_TECHNICAL_REVIEW"}, headers
        )
    )
    return get_success_data(
        api.review_monitoring_plan(
            plan_id, {"decision": "COMPLETE_PUBLIC_COMMENT"}, headers
        )
    )


def rule_on_plan(api, plan_id, decision="APPROVE", headers=REVIEWER, **body):
    payload = {"decision": decision}
    payload.update(body)
    return get_success_data(api.review_monitoring_plan(plan_id, payload, headers))


def take_plan_through_both_review_tracks(
    api, plan_id, headers=REVIEWER, condition_count=0
):
    """Submit a plan, join both review tracks, and approve it."""
    submit_plan(api, plan_id)
    close_both_review_tracks(api, plan_id, headers=headers)
    return rule_on_plan(
        api, plan_id, "APPROVE", headers=headers, condition_count=condition_count
    )


def create_permit(api, project_id, geologic_model_id, **overrides):
    """Draft a Class VI permit application against an accepted model."""
    response = api.create_injection_well_permit(
        create_injection_well_permit_payload(project_id, geologic_model_id, **overrides),
        DEVELOPER,
    )
    return get_success_data(response)


def submit_permit(api, permit_id, submission_note="permit application"):
    response = api.submit_injection_well_permit(
        permit_id, {"submission_note": submission_note}, DEVELOPER
    )
    return get_success_data(response)


def rule_on_permit(api, permit_id, decision, headers=SECOND_REVIEWER, review_note=None):
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(
        api.review_injection_well_permit(permit_id, payload, headers)
    )


def approve_permit(api, permit_id, headers=SECOND_REVIEWER):
    """Submit a drafted permit, open technical review, and approve it."""
    submit_permit(api, permit_id)
    rule_on_permit(api, permit_id, "BEGIN_TECHNICAL_REVIEW", headers=headers)
    return rule_on_permit(api, permit_id, "APPROVE", headers=headers)


def post_instrument(
    api, project_id, instrument_type="TRUST_FUND", face_amount_usd=None
):
    """Post an assurance instrument, which rests wholly unallocated."""
    amount = TRUST_FUND_FACE_AMOUNT_USD if face_amount_usd is None else face_amount_usd
    response = api.create_financial_instrument(
        create_financial_instrument_payload(
            project_id, instrument_type=instrument_type, face_amount_usd=amount
        ),
        DEVELOPER,
    )
    return get_success_data(response)


def allocate_instrument(api, instrument):
    """Run the assurance waterfall guarded on the instrument's own version."""
    response = api.allocate_financial_instrument(
        instrument["id"], allocate_payload(instrument["version"]), DEVELOPER
    )
    return get_success_data(response)


def post_and_allocate_instrument(
    api, project_id, instrument_type="TRUST_FUND", face_amount_usd=None
):
    instrument = post_instrument(
        api, project_id, instrument_type=instrument_type, face_amount_usd=face_amount_usd
    )
    return allocate_instrument(api, instrument)


def authorize_injection(api, project_id, headers=REVIEWER):
    response = api.authorize_injection(
        project_id, {"authorization_note": "all preconditions satisfied"}, headers
    )
    return get_success_data(response)


def advance_construction_through(api, permit_id, steps):
    """Advance the construction dimension one named step at a time."""
    permit = None
    for step in steps:
        permit = get_success_data(
            api.advance_construction(
                permit_id, advance_construction_payload(step), DEVELOPER
            )
        )
    return permit


def record_passing_mit(api, permit_id, annulus_pressure_loss_psi=2.50):
    response = api.record_mit(
        permit_id,
        record_mit_payload(annulus_pressure_loss_psi=annulus_pressure_loss_psi),
        DEVELOPER,
    )
    return get_success_data(response)


def complete_construction_and_activate(
    api, permit_id, annulus_pressure_loss_psi=2.50, headers=REVIEWER
):
    """Drill through to `MIT_PENDING`, pass integrity, complete, and activate."""
    advance_construction_through(api, permit_id, CONSTRUCTION_SEQUENCE[:4])
    record_passing_mit(api, permit_id, annulus_pressure_loss_psi)
    advance_construction_through(api, permit_id, ["COMPLETED"])
    response = api.activate_injection_well_permit(
        permit_id, {"activation_note": "well ready for injection"}, headers
    )
    return get_success_data(response)


def report_period(
    api, permit_id, period_start, period_end, mass_injected_tonnes, **overrides
):
    response = api.report_injection_period(
        permit_id,
        report_injection_period_payload(
            period_start, period_end, mass_injected_tonnes, **overrides
        ),
        DEVELOPER,
    )
    return get_success_data(response)


def void_period(api, period_id, void_reason="metering correction"):
    response = api.void_injection_period(
        period_id, {"void_reason": void_reason}, DEVELOPER
    )
    return get_success_data(response)


def open_remediation_order(
    api, project_id, trigger_type="PLUME_EXCURSION", severity="MAJOR", **overrides
):
    response = api.create_remediation_order(
        create_remediation_order_payload(
            project_id, trigger_type=trigger_type, severity=severity, **overrides
        ),
        REVIEWER,
    )
    return get_success_data(response)


def resolve_remediation_order(api, order_id, remediation_summary="event closed out"):
    response = api.resolve_remediation_order(
        order_id, {"remediation_summary": remediation_summary}, REVIEWER
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def refresh_project(api, project_id, headers=DEVELOPER):
    return get_success_data(api.get_storage_project(project_id, headers))


def refresh_model(api, model_id, headers=DEVELOPER):
    return get_success_data(api.get_geologic_model(model_id, headers))


def refresh_wellbore(api, wellbore_id, headers=DEVELOPER):
    return get_success_data(api.get_legacy_wellbore(wellbore_id, headers))


def refresh_tract(api, tract_id, headers=DEVELOPER):
    return get_success_data(api.get_pore_space_tract(tract_id, headers))


def refresh_permit(api, permit_id, headers=DEVELOPER):
    return get_success_data(api.get_injection_well_permit(permit_id, headers))


def refresh_plan(api, plan_id, headers=DEVELOPER):
    return get_success_data(api.get_monitoring_plan(plan_id, headers))


def refresh_instrument(api, instrument_id, headers=DEVELOPER):
    return get_success_data(api.get_financial_instrument(instrument_id, headers))


def refresh_claim(api, claim_id, headers=DEVELOPER):
    return get_success_data(api.get_tax_credit_claim(claim_id, headers))


# ---------------------------------------------------------------------------
# Tier 1 — a project carrying an accepted geologic model
# ---------------------------------------------------------------------------


def setup_project_with_accepted_model(
    api,
    project_overrides=None,
    model_overrides=None,
    injection_years=DEFAULT_INJECTION_YEARS,
    clock=STARTUP_CLOCK_UTC,
):
    """Project plus a simulated, accepted model — no area of review yet."""
    set_logical_clock(api, clock)
    project = open_project(api, **(project_overrides or {}))
    model = register_geologic_model(
        api, project["id"], project["version"], **(model_overrides or {})
    )
    simulate_plume(api, model["id"], injection_years)
    submit_model(api, model["id"])
    model = rule_on_model(api, model["id"], "ACCEPT")
    return {
        "project": refresh_project(api, project["id"]),
        "model": model,
        "wellbores": [],
        "tracts": [],
        "periods": [],
    }


# ---------------------------------------------------------------------------
# Tier 2 — the area of review published onto the project
# ---------------------------------------------------------------------------


def setup_project_with_finalized_aor(api, wellbore_specs=None, **kwargs):
    """Accepted model with its area of review delineated onto the project.

    Any wellbore specs supplied are registered *before* delineation, so the
    re-screening link of the delineation cascade is the transition that pulls
    them in from `OUT_OF_AOR`.
    """
    ctx = setup_project_with_accepted_model(api, **kwargs)
    for index, spec in enumerate(wellbore_specs or [], start=1):
        ctx["wellbores"].append(
            register_wellbore(
                api, ctx["project"]["id"], f"API-{index:05d}", **spec
            )
        )
    ctx["model"] = finalize_area_of_review(api, ctx["model"]["id"])
    ctx["wellbores"] = [
        refresh_wellbore(api, wellbore["id"]) for wellbore in ctx["wellbores"]
    ]
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def secure_canonical_pore_space(api, ctx, tract_specs=None):
    """Register and execute the tracts that carry consent to its threshold."""
    for spec in CANONICAL_TRACT_SPECS if tract_specs is None else tract_specs:
        spec = dict(spec)
        label = spec.pop("tract_label")
        tract = register_tract(api, ctx["project"]["id"], label, **spec)
        ctx["tracts"].append(execute_tract_lease(api, tract))
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_single_executed_tract(api, ctx, acreage=2400, ownership_pct=100):
    """One tract whose net acreage alone carries consent to its threshold."""
    tract = register_tract(
        api,
        ctx["project"]["id"],
        "T-SOLE",
        acreage=acreage,
        ownership_pct=ownership_pct,
    )
    ctx["tracts"].append(execute_tract_lease(api, tract))
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_approved_monitoring_plan(api, ctx, methods=None, condition_count=0):
    """Add an approved plan to an existing context."""
    plan, methods_created = create_monitoring_plan_with_methods(
        api, ctx["project"]["id"], methods=methods
    )
    ctx["plan"] = take_plan_through_both_review_tracks(
        api, plan["id"], condition_count=condition_count
    )
    ctx["methods"] = methods_created
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — every precondition of injection authorization satisfied
# ---------------------------------------------------------------------------


def setup_project_ready_to_authorize(
    api,
    wellbore_specs=None,
    tract_specs=None,
    methods=None,
    condition_count=0,
    permit_overrides=None,
    face_amount_usd=None,
    **kwargs,
):
    """Delineated area of review, secured pore space, approved plan and permit,
    and a funded instrument — the project sits one call short of authorization.
    """
    ctx = setup_project_with_finalized_aor(api, wellbore_specs=wellbore_specs, **kwargs)
    secure_canonical_pore_space(api, ctx, tract_specs=tract_specs)
    setup_approved_monitoring_plan(
        api, ctx, methods=methods, condition_count=condition_count
    )
    permit = create_permit(
        api,
        ctx["project"]["id"],
        ctx["model"]["id"],
        **(permit_overrides or {}),
    )
    ctx["permit"] = approve_permit(api, permit["id"])
    ctx["instrument"] = post_and_allocate_instrument(
        api, ctx["project"]["id"], face_amount_usd=face_amount_usd
    )
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — injection authorized, then active
# ---------------------------------------------------------------------------


def setup_authorized_project(api, **kwargs):
    """A project whose `status` has reached `INJECTION_AUTHORIZED`."""
    ctx = setup_project_ready_to_authorize(api, **kwargs)
    ctx["project"] = authorize_injection(api, ctx["project"]["id"])
    return ctx


def setup_injection_active_project(api, annulus_pressure_loss_psi=2.50, **kwargs):
    """A project with one activated well, so its `status` is `INJECTION_ACTIVE`."""
    ctx = setup_authorized_project(api, **kwargs)
    ctx["permit"] = complete_construction_and_activate(
        api,
        ctx["permit"]["id"],
        annulus_pressure_loss_psi=annulus_pressure_loss_psi,
    )
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — a populated secure-storage ledger and the claims that read it
# ---------------------------------------------------------------------------


def setup_reported_injection_periods(api, ctx, clock=CLOCK_DURING_INJECTION_YEAR):
    """Report the two canonical half-open periods that touch at one endpoint."""
    if clock is not None:
        set_logical_clock(api, clock)
    ctx["periods"] = [
        report_period(
            api,
            ctx["permit"]["id"],
            PERIOD_1_START,
            PERIOD_1_END,
            PERIOD_1_MASS_TONNES,
            measured_leakage_tonnes=PERIOD_1_LEAKAGE_TONNES,
        ),
        report_period(
            api,
            ctx["permit"]["id"],
            PERIOD_2_START,
            PERIOD_2_END,
            PERIOD_2_MASS_TONNES,
            measured_leakage_tonnes=PERIOD_2_LEAKAGE_TONNES,
        ),
    ]
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_project_with_ledger(api, **kwargs):
    """An active project whose ledger already carries the two canonical periods."""
    ctx = setup_injection_active_project(api, **kwargs)
    return setup_reported_injection_periods(api, ctx)


def setup_draft_tax_credit_claim(api, ctx, tax_year=TAX_YEAR, **claim_overrides):
    """Open a claim against the plan that underwrites the storage report."""
    claim = get_success_data(
        api.create_tax_credit_claim(
            create_tax_credit_claim_payload(
                ctx["project"]["id"],
                ctx["plan"]["id"],
                tax_year=tax_year,
                **claim_overrides,
            ),
            DEVELOPER,
        )
    )
    ctx["claim"] = claim
    return ctx


def setup_submitted_tax_credit_claim(api, ctx, headers=DEVELOPER, **kwargs):
    """Open and submit a claim, recording the submitting developer's identity."""
    if "claim" not in ctx:
        setup_draft_tax_credit_claim(api, ctx, **kwargs)
    ctx["claim"] = get_success_data(
        api.submit_tax_credit_claim(
            ctx["claim"]["id"], {"submission_note": "secure storage report"}, headers
        )
    )
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def verify_tax_credit_claim(api, ctx, decision="ALLOW", headers=VERIFIER):
    ctx["claim"] = get_success_data(
        api.verify_tax_credit_claim(
            ctx["claim"]["id"],
            {"decision": decision, "verification_note": "independent verification"},
            headers,
        )
    )
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Terminal-state shortcuts
# ---------------------------------------------------------------------------


def setup_pisc_project(api, alternative_timeframe_years=None, **kwargs):
    """Close out injection so the project's `status` reaches `PISC`."""
    ctx = setup_injection_active_project(api, **kwargs)
    payload = {}
    if alternative_timeframe_years is not None:
        payload["alternative_timeframe_years"] = alternative_timeframe_years
    ctx["project"] = get_success_data(
        api.begin_pisc(ctx["project"]["id"], payload, DEVELOPER)
    )
    ctx["permit"] = refresh_permit(api, ctx["permit"]["id"])
    return ctx


def setup_frozen_project(api, ctx=None, severity="MAJOR", **kwargs):
    """Open a remediation order severe enough to freeze the project's posture."""
    if ctx is None:
        ctx = setup_injection_active_project(api, **kwargs)
    ctx["remediation_order"] = open_remediation_order(
        api, ctx["project"]["id"], severity=severity
    )
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    ctx["permit"] = refresh_permit(api, ctx["permit"]["id"])
    return ctx
