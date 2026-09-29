"""How a work's two status dimensions, its site footprint and its priority move.

Custody and conservation are independent axes on one artwork row, the site
footprint is a conserved quantity that a de-installation and a reinstallation
must return to its starting value, and the priority score is computed under two
different variants depending on whether a survey was just finalized or the
cycle checkpoint has re-ranked the collection.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.test_users import TEST_USERS


def test_finalizing_a_survey_scores_the_work_under_the_single_assessment_variant(api):
    """PRD §3.9: "Under the **single-assessment** variant, which runs as Cascade A
    hop 2 when a survey is finalized, the source is that very survey and the
    deferral day count is pinned to zero, so the deferral factor is exactly 1.0 and
    the score is the undeferred product; the work's `priority_basis` is set to
    `SINGLE_ASSESSMENT`."

    Design: Difficulty/dual_variant_calc/priority_score_single_assessment_vs_cycle_cohort_variant
    """
    register = fixtures.setup_register(api)
    # BRONZE weights on subscores 2/2/1/1/1 give a weighted defect of 1.55; the urban
    # penalty of 3.0 halves to 1.5 because no axis has failed outright:
    # 100 - 38.75 - 1.5 = 59.75, carried to one decimal place as 59.8.
    finalized = fixtures.setup_assessment_finalized(
        api,
        register["artwork"]["id"],
        assessed_on="2026-03-10",
        surface_score=2,
        structural_score=2,
        coating_score=1,
        mount_score=1,
        graffiti_score=1,
    )
    assert finalized["condition_index"] == 59.8
    assert finalized["recommendation"] == "ROUTINE"

    work = fixtures.read_artwork(api, register["artwork"]["id"])
    # Deficit 40.2 x LANDMARK 1.5 x URBAN 1.25 x deferral 1.0 = 75.375 -> 75.38.
    assert work["treatment_priority_score"] == 75.38
    assert work["priority_basis"] == "SINGLE_ASSESSMENT"
    assert work["conservation_status"] == "MONITORED"


def test_cycle_checkpoint_rescores_the_same_survey_with_deferral(api):
    """PRD §3.9: "Under the **cycle-cohort** variant, which runs at the cycle
    checkpoint, the source is the *earliest* finalized survey of the named cycle
    year for that work — ordered by `assessed_on` ascending and, where two surveys
    share a date, by `created_at` ascending — and the deferral day count is measured
    from that survey's `assessed_on` to the logical clock; the work's
    `priority_basis` is set to `CYCLE_COHORT`."
    PRD §3.9: "The **deferral factor** starts at 1 and grows by 0.004 for each whole
    day between the source survey's `assessed_on` date and the logical clock's date,
    a count that is never negative, and is capped at 1.60 — a ceiling reached after
    150 days of deferral, beyond which further delay no longer improves a work's
    standing in the queue."

    Design: Difficulty/dual_variant_calc/priority_score_single_assessment_vs_cycle_cohort_variant
    """
    register = fixtures.setup_register(api)
    fixtures.setup_assessment_finalized(
        api,
        register["artwork"]["id"],
        assessed_on="2026-03-10",
        surface_score=2,
        structural_score=2,
        coating_score=1,
        mount_score=1,
        graffiti_score=1,
    )
    validate_success(api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"]))

    work = fixtures.read_artwork(api, register["artwork"]["id"])
    # 2026-03-10 to the clock at 2026-08-01 is 144 whole days, so the deferral
    # factor is 1.576: 40.2 x 1.5 x 1.25 x 1.576 = 118.791 -> 118.79.
    assert work["treatment_priority_score"] == 118.79
    assert work["priority_basis"] == "CYCLE_COHORT"
    assert work["condition_index"] == 59.8
    assert work["conservation_status"] == "MONITORED"


def test_relocating_a_flagged_work_leaves_its_conservation_dimension_alone(api):
    """PRD §2.7: "An `Artwork` carries `custody_status`, describing where the object
    physically is (`ON_VIEW`, `IN_STORAGE`, `IN_TREATMENT`, `DEACCESSIONED` or
    `DESTROYED`), and separately `conservation_status`, describing its conservation
    standing (`MONITORED`, `TREATMENT_REQUIRED`, `TREATMENT_IN_PROGRESS` or
    `STABILIZED`)."
    PRD §3.7: "Setting `to_storage` to true withdraws a work from public view,
    moving custody `ON_VIEW → IN_STORAGE`; supplying a `to_site_id` reinstalls a
    stored work, moving custody `IN_STORAGE → ON_VIEW`."

    Design: Difficulty/non_linear_state_machine/artwork_custody_and_conservation_dimensions_move_independently
    """
    register = fixtures.setup_register(api, artist={"moral_rights_waiver_on_file": True})
    # Subscores 3/2/2/1/2 give a weighted defect of 2.15 and an urban penalty of 1.5:
    # 100 - 53.75 - 1.5 = 44.75, carried to one decimal place as 44.8.
    finalized = fixtures.setup_assessment_finalized(api, register["artwork"]["id"])
    assert finalized["condition_index"] == 44.8

    flagged = fixtures.read_artwork(api, register["artwork"]["id"])
    assert flagged["custody_status"] == "ON_VIEW"
    assert flagged["conservation_status"] == "TREATMENT_REQUIRED"

    relocated = validate_success(
        api.relocate_artwork(
            register["artwork"]["id"],
            {
                "to_storage": True,
                "relocation_note": "moved to municipal storage pending treatment",
            },
            TEST_USERS["registrar_headers"],
        )
    )
    assert relocated["custody_status"] == "IN_STORAGE"
    assert relocated["conservation_status"] == "TREATMENT_REQUIRED"
    assert relocated["condition_index"] == 44.8
    # Deficit 55.2 x LANDMARK 1.5 x URBAN 1.25 x deferral 1.0 = 103.50.
    assert relocated["treatment_priority_score"] == 103.50
    assert relocated["moral_rights_status"] == "WAIVED"


def test_storing_a_work_frees_the_site_footprint_it_occupied(api):
    """PRD §3.7: "The vacated site's `installed_units_used` falls by the work's
    `footprint_units`."
    PRD §3.1: "The site's read-only `installed_units_used` starts at zero and is
    maintained as the sum of `footprint_units` over the works whose `site_id` names
    this site and whose `custody_status` is either `ON_VIEW` or `IN_TREATMENT` — a
    work under treatment still occupies its plinth, so it still consumes footprint,
    while a work in storage does not."

    Design: Difficulty/non_linear_state_machine/artwork_custody_and_conservation_dimensions_move_independently
    """
    register = fixtures.setup_register(api, artist={"moral_rights_waiver_on_file": True})
    fixtures.setup_assessment_finalized(api, register["artwork"]["id"])
    assert fixtures.read_site(api, register["site"]["id"])["installed_units_used"] == 6

    validate_success(
        api.relocate_artwork(
            register["artwork"]["id"],
            {"to_storage": True},
            TEST_USERS["registrar_headers"],
        )
    )
    site = fixtures.read_site(api, register["site"]["id"])
    assert site["installed_units_used"] == 0
    assert site["capacity_units"] == 20


def test_de_installing_and_reinstalling_restores_the_site_footprint(api):
    """PRD §3.7: "Reinstallation is the compensating move, and the site-footprint
    invariant must hold again afterwards."
    PRD §3.7: "On success the work's `site_id` becomes the named target and that
    site's `installed_units_used` rises by the work's `footprint_units`."

    Design: Difficulty/compensating_invariant/relocate_out_and_back_restores_site_installed_units
    """
    register = fixtures.setup_register(api, artist={"moral_rights_waiver_on_file": True})
    site_id = register["site"]["id"]
    artwork_id = register["artwork"]["id"]
    assert fixtures.read_site(api, site_id)["installed_units_used"] == 6

    stored = validate_success(
        api.relocate_artwork(
            artwork_id,
            {"to_storage": True, "relocation_note": "de-installed for plaza repaving"},
            TEST_USERS["registrar_headers"],
        )
    )
    assert stored["custody_status"] == "IN_STORAGE"
    assert fixtures.read_site(api, site_id)["installed_units_used"] == 0

    reinstalled = validate_success(
        api.relocate_artwork(
            artwork_id,
            {"to_site_id": site_id, "relocation_note": "reinstalled after repaving"},
            TEST_USERS["registrar_headers"],
        )
    )
    assert reinstalled["custody_status"] == "ON_VIEW"
    assert reinstalled["site_id"] == site_id

    site = fixtures.read_site(api, site_id)
    assert site["installed_units_used"] == 6
    assert site["installed_units_used"] <= site["capacity_units"]


def test_the_round_trip_never_disturbs_the_conservation_dimension(api):
    """PRD §2.7: "A newly accessioned work begins `ON_VIEW` and `MONITORED`."
    PRD §3.1: "A successful accession sets `custody_status` to `ON_VIEW` and
    `conservation_status` to `MONITORED`, raises the site's `installed_units_used`
    by the work's `footprint_units`, and raises the attributed artist's
    `artwork_count` by one."

    Design: Difficulty/compensating_invariant/relocate_out_and_back_restores_site_installed_units
    """
    register = fixtures.setup_register(api, artist={"moral_rights_waiver_on_file": True})
    artwork_id = register["artwork"]["id"]
    assert register["artwork"]["conservation_status"] == "MONITORED"

    stored = validate_success(
        api.relocate_artwork(
            artwork_id, {"to_storage": True}, TEST_USERS["registrar_headers"]
        )
    )
    assert stored["conservation_status"] == "MONITORED"

    reinstalled = validate_success(
        api.relocate_artwork(
            artwork_id,
            {"to_site_id": register["site"]["id"]},
            TEST_USERS["registrar_headers"],
        )
    )
    assert reinstalled["conservation_status"] == "MONITORED"
    assert reinstalled["condition_index"] is None
    assert reinstalled["treatment_priority_score"] is None
    assert reinstalled["priority_basis"] == "NONE"
