"""Draw amount calculations: progress-draw retainage withholding and the
final-draw variant (no new retainage).

Queue B (calculations section). The aerial estimate result and the
PRORATED/SHORT_RATE warranty divergence are owned by their difficulty
instances (test_01).
"""
from test_helpers import (
    validate_success, TEST_USERS, setup_in_production_job, create_draw_payload,
)

PM = TEST_USERS["production_manager_headers"]

SHINGLE_10 = [{"trade": "SHINGLE", "squares": 10, "unit_price_cents": 10000, "waste_factor_pct": 0.10}]


def test_progress_draw_retainage_and_net(api):
    """PRD §3.7: "For a non-final draw the `retainage_cents` is the
    `gross_eligible_cents` multiplied by the job's `retainage_pct`, rounded
    half-up to a whole cent."
    PRD §3.7: "The `net_disbursed_cents` is the `gross_eligible_cents` minus the
    `retainage_cents`."

    Design: Corner/calculations/draw_progress_retainage_correct
    """
    job_id, info = setup_in_production_job(line_items=SHINGLE_10)  # contract 110000, retainage 0.10
    data = validate_success(api.create_draw(create_draw_payload(
        job_id=job_id, cumulative_pct=0.5, expected_job_version=info["job_version"]), PM),
        expected_status=201)
    # gross-to-date = round(110000*0.5)=55000; eligible=55000-0=55000.
    assert data["gross_eligible_cents"] == 55000
    assert data["retainage_cents"] == 5500   # round(55000*0.10)
    assert data["net_disbursed_cents"] == 49500


def test_final_draw_withholds_no_retainage(api):
    """PRD §3.7: "The draw is final, recorded in `is_final`, exactly when the
    `cumulative_pct` equals 1.0."
    PRD §3.7: "for a final draw the `retainage_cents` is 0, because the final
    draw withholds nothing new (the retainage held to date is released
    separately at warranty activation)."

    Design: Corner/calculations/final_draw_withholds_no_retainage
    """
    job_id, info = setup_in_production_job(line_items=SHINGLE_10)  # contract 110000
    data = validate_success(api.create_draw(create_draw_payload(
        job_id=job_id, cumulative_pct=1.0, expected_job_version=info["job_version"]), PM),
        expected_status=201)
    assert data["is_final"] is True
    assert data["retainage_cents"] == 0
    # eligible = round(110000*1.0) - 0 = 110000; net = 110000 - 0.
    assert data["net_disbursed_cents"] == 110000
