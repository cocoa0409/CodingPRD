"""Single writes whose consequences travel three and four entities outward."""

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_field_sequence,
    assert_null_fields,
    assert_page,
    assert_score,
)
from test_helpers.constants import FORFEITED_BOND_NAME_PREFIX
from test_helpers.factories import enforcement_payload

DEEP_WELL = dict(
    spud_year=1969,
    total_depth_ft=8000,
    casing_strings=3,
    methane_scfd=310,
    groundwater_depth_ft=180,
    population_within_1000ft=3,
    surface_disturbance_acres=1.25,
)
QUIET_SHALLOW_WELL = dict(
    spud_year=1988,
    total_depth_ft=2500,
    casing_strings=2,
    methane_scfd=50,
    groundwater_depth_ft=600,
    population_within_1000ft=1,
    surface_disturbance_acres=0.5,
)


def _enforce(api, operator_id, action, memo):
    """Act against an operator with a freshly re-read version."""
    version = fx.read_operator(api, operator_id)["version"]
    response = api.operator_enforcement(
        operator_id, enforcement_payload(action, version, memo), users.ADMIN
    )
    assert response.status_code == 200, "enforcement failed: %r" % (response.json(),)
    return response.json()["data"]


def _insolvent_operator_with_two_wells(api):
    """An INSOLVENT operator still holding a shallow and a deep producing well."""
    operator = fx.make_operator(
        api, name="Ghost Creek Energy", region_code="TX", bond_amount_cents=3000000
    )
    shallow = fx.make_well(api, operator["id"])
    deep = fx.make_well(api, operator["id"], **DEEP_WELL)
    _enforce(
        api,
        operator["id"],
        "DECLARE_INSOLVENT",
        "receiver appointed; no responsible party for plugging liability",
    )
    return {"operator": operator, "shallow": shallow, "deep": deep}


def test_forfeiting_the_bond_walks_operator_to_funding_source_to_wells(api):
    """One enforcement call moves money into a new source and orphans both wells.

    The request body names an action and a version and nothing else, yet the write
    lands on the operator, then on a funding source that did not exist before, then on
    every well the operator still holds.

    PRD: "First, a new funding source is created with `kind` `FORFEITED_BOND`, `name`
    formed as the literal text `FORFEITED BOND ` followed by the operator's `name`,
    `authorized_cents` equal to the operator's pre-forfeiture `bond_amount_cents`"

    Design: Difficulty/transitive_cascade/bond_forfeiture_cascades_operator_to_funding_source_to_wells_to_scores
    """
    bundle = _insolvent_operator_with_two_wells(api)
    operator_id = bundle["operator"]["id"]

    forfeited = _enforce(
        api,
        operator_id,
        "FORFEIT_BOND",
        "bond called and forfeited to the oilfield cleanup program",
    )
    assert_fields(
        forfeited,
        status="REVOKED",
        bond_amount_cents=0,
        bond_forfeited_at="2026-08-01T00:00:00Z",
    )

    sources = assert_page(
        api.list_funding_sources(
            users.FUNDING, {"kind": "FORFEITED_BOND", "bond_operator_id": operator_id}
        ),
        1,
        expected_total=1,
    )
    source = sources[0]
    assert_fields(
        source,
        kind="FORFEITED_BOND",
        name=FORFEITED_BOND_NAME_PREFIX + "Ghost Creek Energy",
        status="ACTIVE",
        bond_operator_id=operator_id,
        expires_at="2036-07-29T00:00:00Z",
    )
    assert_cents(source["authorized_cents"], 3000000, "authorized_cents")
    assert_cents(source["committed_cents"], 0, "committed_cents")
    assert sorted(source["allowable_cost_categories"]) == ["PLUGGING", "RECLAMATION"], (
        "expected the forfeited bond to fund plugging and reclamation, got %r"
        % (source["allowable_cost_categories"],)
    )

    assert_fields(fx.read_well(api, bundle["shallow"]["id"]), status="ORPHAN_CANDIDATE")
    assert_fields(fx.read_well(api, bundle["deep"]["id"]), status="ORPHAN_CANDIDATE")


def test_the_forfeiture_cascade_reaches_scores_and_counters_it_never_names(api):
    """The fourth hop rewrites two priority scores per well and three operator figures.

    Both scores of both wells are recomputed on the way through, and the operator's
    orphan counter lands at 2 - none of which the request body could have named.

    PRD: "Fourth, caused by the third, every well of this operator whose `status` is
    `PRODUCING` or `INACTIVE` transitions to `ORPHAN_CANDIDATE`, each such well's two
    priority scores are recomputed, and `orphan_candidate_count` is recomputed."

    Design: Difficulty/transitive_cascade/bond_forfeiture_cascades_operator_to_funding_source_to_wells_to_scores
    """
    bundle = _insolvent_operator_with_two_wells(api)
    operator_id = bundle["operator"]["id"]

    _enforce(api, operator_id, "FORFEIT_BOND", "bond called and forfeited")

    shallow = fx.read_well(api, bundle["shallow"]["id"])
    deep = fx.read_well(api, bundle["deep"]["id"])
    assert_score(shallow["screening_score"], 59.90, "shallow screening_score")
    assert_score(shallow["remediation_score"], 81.00, "shallow remediation_score")
    assert_score(deep["screening_score"], 50.35, "deep screening_score")
    assert_score(deep["remediation_score"], 39.70, "deep remediation_score")

    operator = fx.read_operator(api, operator_id)
    assert_fields(operator, orphan_candidate_count=2, active_well_count=2)
    assert_cents(operator["required_bond_cents"], 1250000, "required_bond_cents")


def _delinquent_operator_with_a_reported_deep_job(api):
    """A DELINQUENT operator whose deep well is one review away from being plugged."""
    operator = fx.make_operator(
        api, name="Cimarron Tail Assets", region_code="OK", bond_amount_cents=1000000
    )
    keep = fx.make_well(api, operator["id"], **QUIET_SHALLOW_WELL)
    plug = fx.make_well(api, operator["id"], **DEEP_WELL)

    determination = fx.open_determination(
        api, plug["id"], inspector_notes="deep well, no operator of record on site"
    )
    fx.submit_determination(api, determination["id"])
    fx.decide_determination(
        api,
        determination["id"],
        "CONFIRM",
        "idle 999 months, zero production, screening 50.35",
    )

    procurement = fx.make_active_contract(
        api, region_code="OK", scope_description="plug and abandon 1 deep orphan well"
    )
    fx.authorize_site_access(api, plug["id"])
    job = fx.make_plugging_job(
        api,
        plug["id"],
        procurement["contract"]["id"],
        scheduled_start="2026-09-01T00:00:00Z",
    )
    fx.mobilize(api, job["id"])
    job = fx.file_field_report(
        api,
        job["id"],
        downhole_conditions="three plugs set; 500 ft of 5.5 inch casing recovered",
        plug_intervals=[
            {"top_ft": 7700, "bottom_ft": 8000, "sacks": 50},
            {"top_ft": 900, "bottom_ft": 1100, "sacks": 30},
            {"top_ft": 0, "bottom_ft": 100, "sacks": 20},
        ],
    )
    return {"operator": operator, "keep": keep, "plug": plug, "job": job}


def test_accepting_the_plugging_cures_a_delinquency_three_hops_away(api):
    """Acceptance drops the deep well out of the assurance base and restores standing.

    The operator was short because the 8000 ft well demanded 1000000 cents of the
    1250000 requirement; the accepted plugging removes that well from the base, the
    requirement falls to 250000, and the 1000000 already posted now covers it.

    PRD: "Fourth, caused by the third, an operator standing at `DELINQUENT` whose
    `bond_amount_cents` now equals or exceeds the freshly reduced `required_bond_cents`
    transitions `DELINQUENT → ACTIVE`."

    Design: Difficulty/transitive_cascade/plugging_acceptance_cascades_job_to_well_to_operator_standing_and_tasks
    """
    bundle = _delinquent_operator_with_a_reported_deep_job(api)
    operator_id = bundle["operator"]["id"]

    before = fx.read_operator(api, operator_id)
    assert_fields(before, status="DELINQUENT")
    assert_cents(before["required_bond_cents"], 1250000, "required_bond_cents before")

    accepted = fx.review_job(
        api,
        bundle["job"]["id"],
        "ACCEPT",
        "plugs verified by tag; downhole documentation complete",
    )
    assert_fields(
        accepted, status="PLUGGED", plugging_accepted_at="2026-08-01T00:00:00Z"
    )
    assert_cents(accepted["actual_cost_cents"], 6328179, "actual_cost_cents")

    assert_fields(fx.read_well(api, bundle["plug"]["id"]), status="PLUGGED")

    after = fx.read_operator(api, operator_id)
    assert_fields(
        after, status="ACTIVE", active_well_count=1, orphan_candidate_count=0
    )
    assert_cents(after["required_bond_cents"], 250000, "required_bond_cents after")

    assert_fields(fx.read_well(api, bundle["keep"]["id"]), status="PRODUCING")


def test_accepting_the_plugging_materialises_the_three_reclamation_tasks(api):
    """The same acceptance creates three surface obligations that did not exist before.

    The task list is empty right up to the review and holds exactly three PENDING rows
    afterwards, ordered by task type.

    PRD: "First, exactly three reclamation tasks are created for the job, with
    `task_type` `EQUIPMENT_REMOVAL`, `PIT_CLOSURE` and `REVEGETATION` respectively,
    each at `status` `PENDING`."

    Design: Difficulty/transitive_cascade/plugging_acceptance_cascades_job_to_well_to_operator_standing_and_tasks
    """
    bundle = _delinquent_operator_with_a_reported_deep_job(api)
    job_id = bundle["job"]["id"]

    assert_page(api.list_reclamation_tasks(job_id, users.INSPECTOR), 0, expected_total=0)

    fx.review_job(api, job_id, "ACCEPT", "plugs verified by tag")

    tasks = assert_page(
        api.list_reclamation_tasks(job_id, users.INSPECTOR), 3, expected_total=3
    )
    assert_field_sequence(
        tasks, "task_type", ["EQUIPMENT_REMOVAL", "PIT_CLOSURE", "REVEGETATION"]
    )
    for task in tasks:
        assert_fields(task, status="PENDING", inspection_round=0, job_id=job_id)
        assert_null_fields(task, "inspected_by_user_id", "completed_at")
