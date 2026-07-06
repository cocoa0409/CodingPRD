"""Dual-variant calculations: provisional required wage, and PERM-based vs
self-petition priority dates (PRD §3.4, §3.7).

Queue A / Difficulty — rule `dual_variant_calc`.
"""
from test_helpers import (
    api_client, validate_success, TEST_USERS,
    create_employer, create_lca, create_beneficiary, create_i140_petition,
    submit_i140_petition, setup_certified_perm_case, set_clock,
    make_employer_agent_headers,
)

DOL = TEST_USERS["dol_analyst_headers"]


def test_provisional_required_wage_at_creation_is_max_of_prevailing_and_offered(api):
    """PRD §3.4: "`required_wage_cents` is the greater of `prevailing_wage_cents`
    and `offered_wage_cents`."
    PRD §3.4: "While the application is in `DRAFT` this figure is **provisional**:
    it is recomputed on every read from the application's current
    `prevailing_wage_cents`, so editing that field before certification changes
    it."

    Design: Difficulty/dual_variant_calc/lca_required_wage_provisional_vs_final
    """
    emp = create_employer()
    lca = create_lca(emp["id"], prevailing_wage_cents=10000000, offered_wage_cents=11000000,
                     area_wage_map={"AREA_A": 10000000})
    assert lca["required_wage_cents"] == 11000000


def test_provisional_required_wage_recomputes_after_editing_prevailing(api):
    """PRD §3.4: "While the application is in `DRAFT` this figure is **provisional**:
    it is recomputed on every read from the application's current
    `prevailing_wage_cents`, so editing that field before certification changes
    it."
    PRD §3.4: "Editing recomputes the provisional `required_wage_cents` and the
    `aggregate_wage_obligation_cents`."

    Design: Difficulty/dual_variant_calc/lca_required_wage_provisional_vs_final
    """
    emp = create_employer()
    hdr = make_employer_agent_headers(emp["id"])
    lca = create_lca(emp["id"], prevailing_wage_cents=10000000, offered_wage_cents=11000000,
                     area_wage_map={"AREA_A": 10000000})
    prov0 = lca["required_wage_cents"]
    assert prov0 == 11000000
    patched = validate_success(api.patch_lca(lca["id"], {"prevailing_wage_cents": 13000000}, hdr), 200)
    assert patched["required_wage_cents"] == 13000000  # max(13000000, offered 11000000)


def test_perm_based_i140_inherits_perm_priority_date(api):
    """PRD §3.7: "A **PERM-based** petition — one that has a non-null
    `perm_case_id` and whose `category` is `EB2` or `EB3` — inherits the
    underlying PERM case's `priority_date`, which is the earlier
    labor-certification filing date and therefore a better queue position."
    PRD §3.7: "On submission the system stamps `filed_date` to the current clock
    and sets the petition's `priority_date` according to its lineage."

    Design: Difficulty/dual_variant_calc/i140_priority_date_perm_based_vs_self_petition
    """
    employer, pwd, perm_case = setup_certified_perm_case()  # priority_date == 2026-07-10
    assert perm_case["priority_date"] == "2026-07-10T00:00:00Z"
    ben = create_beneficiary(employer["id"])
    i140_perm = create_i140_petition(employer["id"], ben["id"], category="EB2",
                                     perm_case_id=perm_case["id"])
    set_clock("2026-08-01T00:00:00Z")
    submitted = submit_i140_petition(employer["id"], i140_perm["id"])
    assert submitted["priority_date"] == "2026-07-10T00:00:00Z"


def test_self_petition_i140_uses_own_filed_date_and_diverges_from_perm_based(api):
    """PRD §3.7: "A **self-petition** — one whose `category` is `EB1`, or one with
    no `perm_case_id` — instead uses this petition's own `filed_date`."
    PRD §3.7: "(For otherwise identical filing timestamps the two rules diverge
    whenever the PERM was filed before the I-140.)"

    Design: Difficulty/dual_variant_calc/i140_priority_date_perm_based_vs_self_petition
    """
    employer, pwd, perm_case = setup_certified_perm_case()  # perm priority_date 2026-07-10
    ben = create_beneficiary(employer["id"])
    i140_perm = create_i140_petition(employer["id"], ben["id"], category="EB2",
                                     perm_case_id=perm_case["id"])
    i140_self = create_i140_petition(employer["id"], ben["id"], category="EB1")
    set_clock("2026-08-01T00:00:00Z")
    pd_perm = submit_i140_petition(employer["id"], i140_perm["id"])["priority_date"]
    pd_self = submit_i140_petition(employer["id"], i140_self["id"])["priority_date"]
    assert pd_self == "2026-08-01T00:00:00Z"
    assert pd_perm == "2026-07-10T00:00:00Z"
    assert pd_self != pd_perm
