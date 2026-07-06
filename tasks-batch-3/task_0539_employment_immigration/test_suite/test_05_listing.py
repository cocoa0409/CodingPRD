"""List pagination, FK-reverse filtered listing, and computed-field reads (PRD §2.3, §3).

Queue B / Corner — section `endpoints`.
"""
from test_helpers import (
    api_client, validate_success, validate_paginated, TEST_USERS,
    create_employer, create_pending_pwd, create_beneficiary, create_cap_program,
    create_registration, create_lca, setup_recruiting_perm_case, add_recruitment_step,
    make_employer_agent_headers,
)

USCIS = TEST_USERS["uscis_officer_headers"]


def test_pwd_list_pagination_limit_offset_total_count_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter is the number of items to skip and defaults to 0."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/pwd_list_pagination_limit_offset_total_count_has_more
    """
    emp = create_employer()
    for area in ("AREA_A", "AREA_B", "AREA_C"):
        create_pending_pwd(emp["id"], area_code=area)
    hdr = make_employer_agent_headers(emp["id"])

    data, meta = validate_paginated(api.list_pwds(hdr, params={"employer_id": emp["id"], "limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data, meta = validate_paginated(api.list_pwds(hdr, params={"employer_id": emp["id"], "limit": 2, "offset": 2}))
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_recruitment_steps_filtered_list_by_perm_case_id(api):
    """PRD §3.3: "Recruitment steps can be listed and filtered by `perm_case_id`
    or `status`".

    Design: Corner/endpoints/recruitment_steps_filtered_list_by_perm_case_id
    """
    employer, pwd, pc = setup_recruiting_perm_case()
    hdr = make_employer_agent_headers(employer["id"])
    step = add_recruitment_step(employer["id"], pc["id"], step_type="JOB_ORDER",
                                start_date="2026-05-01T00:00:00Z", end_date="2026-05-31T00:00:00Z")
    data, meta = validate_paginated(api.list_recruitment_steps(hdr, params={"perm_case_id": pc["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == step["id"]


def test_lca_get_returns_computed_required_and_aggregate_fields(api):
    """PRD §3.4: "`required_wage_cents` is the greater of `prevailing_wage_cents`
    and `offered_wage_cents`."
    PRD §3.4: "A new application's `paf_status` starts at `OPEN`."

    Design: Corner/endpoints/lca_get_returns_computed_required_and_aggregate_fields
    """
    emp = create_employer()
    lca = create_lca(emp["id"], prevailing_wage_cents=10000000, offered_wage_cents=12000000,
                     worksite_areas=["AREA_A"], area_wage_map={"AREA_A": 10000000})
    hdr = make_employer_agent_headers(emp["id"])
    fetched = validate_success(api.get_lca(lca["id"], hdr), 200)
    assert fetched["required_wage_cents"] == 12000000
    assert fetched["aggregate_wage_obligation_cents"] == 10000000
    assert fetched["paf_status"] == "OPEN"


def test_registrations_filtered_list_by_beneficiary_id(api):
    """PRD §3.5: "Registrations can be listed and filtered by `employer_id`,
    `beneficiary_id`, `fiscal_year`, or `status`".

    Design: Corner/endpoints/registrations_filtered_list_by_beneficiary_id
    """
    emp = create_employer()
    ben = create_beneficiary(emp["id"])
    create_cap_program(2027, 5)
    reg = create_registration(emp["id"], ben["id"], 2027)
    data, meta = validate_paginated(api.list_registrations(USCIS, params={"beneficiary_id": ben["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == reg["id"]
