"""Slip-and-fall claims: coverage window, documentation score gate, bundle."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_claim_payload,
    setup_active_per_push, setup_storm_event, set_clock,
    post_observation, verify_event, verify_event_with_two_sources,
    setup_completed_visit, setup_billable_visit, schedule_visit, run_visit,
    upload_photo, accept_photo, log_material, setup_claim,
    make_client_headers,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
CREW = TEST_USERS["crew_lead_headers"]

_OBS = [("NOAA", "2026-12-10T07:30:00Z", 2.0), ("DTN", "2026-12-10T08:00:00Z", 2.1)]


def test_claim_review_outside_covered_season_returns_window_expired(api):
    """PRD §3.8: "Review resolves coverage first: some contract in `ACTIVE`, `SUSPENDED`, or `EXPIRED` must cover the site with `season_start` at or before `incident_at` and `incident_at` at or before `season_end`, failing as `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Corner/validations/claim_review_outside_covered_season_returns_window_expired
    """
    ctx = setup_active_per_push(client_name="Claim Co", require_photo_verification=False)
    claim = setup_claim(ctx, ctx["site"]["id"], "2026-06-15T14:00:00Z",
                        severity="NEAR_MISS",
                        description="Summer incident, outside coverage")
    assert claim["status"] == "FILED"

    validate_error(api.review_claim(claim["id"], ADJUSTER),
                   ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)


def test_claim_document_gate_below_min_score(api):
    """PRD §3.8: "The `STANDARD` weights are 15 for the before photo, 25 for the after photo, 20 for material, 20 for timeliness, and 20 for weather"
    PRD §3.8: "Documenting the claim — moving `DOCUMENTATION_REVIEW` to `DOCUMENTED` — requires that selected score to be at least 60, failing as `ERR_DOCUMENTATION_INCOMPLETE`."
    PRD §3.8: "The selected `documentation_completeness_score` is the `STRICT` figure when severity is `INJURY_REPORTED` and the `STANDARD` figure otherwise."

    Design: Corner/validations/claim_document_gate_below_min_score
    """
    ctx = setup_active_per_push(client_name="Doc Gate Co", trigger_depth_inches=1.0,
                                completion_target_minutes=480)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    # One on-time visit (timeliness + weather only): no photos, no materials.
    setup_billable_visit(ctx, event, _OBS)

    claim = setup_claim(ctx, ctx["site"]["id"], "2026-12-10T07:30:00Z",
                        severity="NEAR_MISS",
                        description="Pedestrian slipped near entrance")
    reviewed = validate_success(api.review_claim(claim["id"], ADJUSTER), 200)
    assert reviewed["status"] == "DOCUMENTATION_REVIEW"
    assert reviewed["documentation_completeness_score"] == 40, (
        "STANDARD weights: timeliness 20 + weather 20 only")

    validate_error(api.document_claim(claim["id"], ADJUSTER),
                   ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE)


def test_documentation_bundle_computed_read_and_document_transition(api):
    """PRD §3.8: "For litigation support, a computed documentation bundle assembles the claim's `claim_id`, its `documentation_contract_id` and `storm_event_id`, the `matching_visit_ids` at the site under the linked event, the associated `photo_ids` and `material_application_ids`, the `weather_observation_ids` behind verification, and both `score_standard` and `score_strict`."
    PRD §3.8: "The `STANDARD` weights are 15 for the before photo, 25 for the after photo, 20 for material, 20 for timeliness, and 20 for weather; the `STRICT` weights are 30, 40, 10, 10, and 10 respectively, so photo evidence carries seventy of the hundred points and a claim without photos cannot pass."
    PRD §3.8: "Documenting the claim — moving `DOCUMENTATION_REVIEW` to `DOCUMENTED` — requires that selected score to be at least 60"

    Design: Corner/endpoints/documentation_bundle_computed_read_and_document_transition
    """
    ctx = setup_active_per_push(client_name="Bundle Co", trigger_depth_inches=1.0,
                                completion_target_minutes=480)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    o1 = post_observation(event["id"], "NOAA", "2026-12-10T07:30:00Z", 2.0)
    o2 = post_observation(event["id"], "DTN", "2026-12-10T08:00:00Z", 2.1)

    visit = schedule_visit(event["id"], ctx["contract_site"]["id"])
    set_clock("2026-12-10T09:05:00Z")
    get_success_data(api.start_visit(visit["id"], CREW))
    photo = upload_photo(visit["id"], "AFTER", "s3://proof/bundle-after.jpg")
    accept_photo(photo["id"])
    material = log_material(visit["id"], "ROCK_SALT", 50.0)
    set_clock("2026-12-10T10:00:00Z")
    get_success_data(api.complete_visit(visit["id"], CREW))
    verify_event(event["id"])

    claim = setup_claim(ctx, ctx["site"]["id"], "2026-12-10T07:45:00Z",
                        severity="NEAR_MISS",
                        description="Slip near entrance during storm")
    reviewed = validate_success(api.review_claim(claim["id"], ADJUSTER), 200)
    assert reviewed["documentation_contract_id"] == ctx["contract"]["id"]
    assert reviewed["storm_event_id"] == event["id"]
    assert reviewed["documentation_completeness_score"] == 85, (
        "NEAR_MISS selects STANDARD: after 25 + material 20 + timeliness 20 "
        "+ weather 20 (no BEFORE photo)")

    bundle = validate_success(api.get_documentation_bundle(claim["id"], ADJUSTER), 200)
    assert bundle["claim_id"] == claim["id"]
    assert bundle["documentation_contract_id"] == ctx["contract"]["id"]
    assert bundle["storm_event_id"] == event["id"]
    assert bundle["matching_visit_ids"] == [visit["id"]]
    assert bundle["photo_ids"] == [photo["id"]]
    assert bundle["material_application_ids"] == [material["id"]]
    assert set(bundle["weather_observation_ids"]) >= {o1["id"], o2["id"]}
    assert bundle["score_standard"] == 85
    assert bundle["score_strict"] == 70, "40 + 10 + 10 + 10"

    documented = validate_success(api.document_claim(claim["id"], ADJUSTER), 200)
    assert documented["status"] == "DOCUMENTED", "85 >= 60 passes the gate"
