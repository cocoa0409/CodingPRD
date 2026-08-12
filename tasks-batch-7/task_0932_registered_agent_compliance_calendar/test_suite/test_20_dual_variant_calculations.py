"""Two jurisdictions, identical inputs, different answers."""
from test_helpers import (
    DE_RULE_FULL,
    NY_RULE_FULL,
    SOP,
    accept_appointment,
    activate_registration,
    assert_same_instant,
    new_client,
    new_entity,
    new_home_registration,
    new_obligation,
    propose_appointment,
    publish_rule,
    read_registration,
    receive_sop,
    set_clock,
    setup_active_home_registration,
    validate_success,
)

SHARED_SHARE_FACTS = {
    "authorized_shares": 8000,
    "issued_shares": 4000,
    "total_gross_assets_cents": 12000000,
    "annual_gross_receipts_cents": 500000000,
}


def _two_state_scene():
    """Two clients, two entities carrying byte-identical share and asset facts, each
    with its own ACTIVE home registration — one in DE, one in NY."""
    de_rule = publish_rule(DE_RULE_FULL)
    ny_rule = publish_rule(NY_RULE_FULL)
    client_de = new_client()
    client_ny = new_client(
        legal_name="Empire Holdings", billing_email="ap@empire.example"
    )
    entity_de = new_entity(client_de["id"], **SHARED_SHARE_FACTS)
    entity_ny = new_entity(
        client_ny["id"],
        legal_name="Eastwind Widgets LLC",
        home_state_code="NY",
        **SHARED_SHARE_FACTS,
    )
    scene = {"de_rule": de_rule, "ny_rule": ny_rule}
    for key, entity in (("de", entity_de), ("ny", entity_ny)):
        registration = new_home_registration(entity["id"])
        appointment = propose_appointment(registration)
        accept_appointment(appointment["id"])
        scene[f"registration_{key}"] = activate_registration(registration["id"])
        scene[f"entity_{key}"] = entity
    return scene


def test_identical_share_facts_price_differently_under_the_two_bases(api):
    """PRD §3.5: "Under `AUTHORIZED_SHARES_TIERS`, the rule's `authorized_shares_tiers`
    are considered in ascending order of `up_to_shares`, with any tier whose
    `up_to_shares` is null placed last. The server walks that ordered list and returns
    the `tax_cents` of the first tier whose `up_to_shares` is null or is greater than or
    equal to the entity's `authorized_shares`."
    PRD §3.5: "Under `ASSUMED_PAR_VALUE`, the server first computes an assumed par
    capital: if the entity's `authorized_shares` is 0 the assumed par capital is 0,
    otherwise it is the entity's `total_gross_assets_cents` multiplied by its
    `issued_shares` and divided by its `authorized_shares`, **rounded half up to a whole
    cent at that point**. The raw tax is then the assumed par capital multiplied by the
    rule's `assumed_par_value_rate_bps` and divided by 10000, again rounded half up to a
    whole cent."
    PRD §3.5: "for `FRANCHISE_TAX` it is the rule's `franchise_tax_filing_fee_cents`;
    and for `BOI_INITIAL` and `BOI_UPDATE` it is 0, because the beneficial-ownership
    registry charges no state filing fee."

    Design: Difficulty/dual_variant_calc/franchise_tax_share_tiers_versus_assumed_par_value
    """
    scene = _two_state_scene()

    obligation_de = new_obligation(
        scene["registration_de"]["id"], "FRANCHISE_TAX", 2027
    )
    obligation_ny = new_obligation(
        scene["registration_ny"]["id"], "FRANCHISE_TAX", 2027
    )

    # 8000 authorized shares falls in Delaware's second tier, whose ceiling is 10000.
    assert obligation_de["franchise_tax_cents"] == 25000
    # New York: 12000000 * 4000 / 8000 = 6000000 assumed par capital;
    # 6000000 * 35 / 10000 = 21000, inside the [17500, 2000000] clamp.
    assert obligation_ny["franchise_tax_cents"] == 21000

    assert obligation_de["state_fee_cents"] == 5000
    assert obligation_ny["state_fee_cents"] == 900
    # Each obligation is the first of its own client, so neither is discounted.
    assert obligation_de["service_fee_cents"] == 4900
    assert obligation_ny["service_fee_cents"] == 4900


def test_the_two_jurisdictions_produce_different_totals_and_different_due_dates(api):
    """PRD §3.5: "`total_due_cents` is `state_fee_cents` plus `franchise_tax_cents` plus
    `late_fee_cents` plus `service_fee_cents`."
    PRD §3.4: "When the pinned rule's `annual_report_basis` is `ANNIVERSARY_MONTH_DAY`,
    the month is the month of the entity's `formation_date` and the day is the day of
    the entity's `formation_date`, reduced to the last day of that month in the
    obligation's `period_year` if the formation day exceeds it."
    PRD §3.4: "The determination date is the current logical clock date; it is stored on
    the row as `rule_determination_date`, and the rule version selected for the
    registration's `state_code` at that date has its `id` stored as `governing_rule_id`."

    Design: Difficulty/dual_variant_calc/franchise_tax_share_tiers_versus_assumed_par_value
    """
    scene = _two_state_scene()

    obligation_de = new_obligation(
        scene["registration_de"]["id"], "FRANCHISE_TAX", 2027
    )
    obligation_ny = new_obligation(
        scene["registration_ny"]["id"], "FRANCHISE_TAX", 2027
    )

    # 5000 + 25000 + 0 late + 4900 = 34900.
    assert obligation_de["total_due_cents"] == 34900
    # 900 + 21000 + 0 late + 4900 = 26800.
    assert obligation_ny["total_due_cents"] == 26800

    # Delaware fixes 3/1 for every company on its rolls; 2027-03-01 is a Monday.
    assert obligation_de["due_date"] == "2027-03-01"
    # New York anchors on the formation anniversary 2027-01-31, a Sunday, which rolls
    # forward to Monday 2027-02-01.
    assert obligation_ny["due_date"] == "2027-02-01"

    assert obligation_de["governing_rule_id"] == scene["de_rule"]["id"]
    assert obligation_ny["governing_rule_id"] == scene["ny_rule"]["id"]


def test_litigation_and_ordinary_papers_get_different_forward_deadlines(api):
    """PRD §3.9: "A `LITIGATION` document gets 4 business hours — half a business day,
    so a Friday-morning receipt lands Friday afternoon and a Friday-afternoon receipt
    lands Monday morning. An `ORDINARY` document gets 16 business hours, which is two
    full business days, so a Friday receipt lands on Tuesday."
    PRD §2.5: "The business day runs from 09:00 UTC inclusive to 17:00 UTC exclusive,
    giving 8 business hours per business day."

    Design: Difficulty/dual_variant_calc/sop_forward_deadline_ordinary_versus_litigation
    """
    scene = setup_active_home_registration(DE_RULE_FULL)
    set_clock("2026-06-05T14:00:00Z")

    litigation = validate_success(
        api.create_sop_document(
            scene["registration"]["id"],
            {
                "sop_class": "LITIGATION",
                "plaintiff_name": "Acme Trading Co",
                "court_case_number": "N26C-0417",
            },
            SOP,
        ),
        201,
    )
    ordinary = receive_sop(scene["registration"]["id"], "ORDINARY")

    # Friday 14:00 plus 4 business hours: 3 hours to 17:00 Friday, then 1 hour from
    # 09:00 Monday lands at 2026-06-08T10:00Z.
    assert_same_instant(
        litigation["forward_deadline_at"],
        "2026-06-08T10:00:00Z",
        "litigation forward_deadline_at",
    )
    # Friday 14:00 plus 16 business hours: 3 hours Friday, 8 hours Monday, then 5
    # hours from 09:00 Tuesday lands at 2026-06-09T14:00Z.
    assert_same_instant(
        ordinary["forward_deadline_at"],
        "2026-06-09T14:00:00Z",
        "ordinary forward_deadline_at",
    )


def test_ordinary_papers_received_after_the_litigation_papers_are_not_deferred(api):
    """PRD §2.5: "Every "current instant" and "current date" this document refers to —
    including the `created_at` and `updated_at` stamps of Section 2.4, every `*_at`
    instant such as `received_at`, `scanned_at`, `forwarded_at` and `acknowledged_at`,
    and every `*_on` date such as `qualified_on`, `closed_on`, `submitted_on`,
    `satisfied_on`, `sent_on`, `admin_dissolved_on`, `outcome_recorded_on`,
    `accepted_on` and `assessment_date` — is read from the logical clock."
    PRD §3.9: "Every `ORDINARY` document on that registration whose `status` is
    `RECEIVED` or `SCANNED` — that is, every ordinary document not yet forwarded — has
    its `forward_deadline_at` advanced by a further 8 business hours along the same
    cursor, has `deferred` set true, and has `deferral_count` increased by one."
    PRD §3.9: "That flag is true exactly while at least one `LITIGATION` document on the
    registration is in status `RECEIVED`, `SCANNED`, `FORWARDED` or `ESCALATED`, and
    false otherwise; it is re-evaluated whenever a litigation document leaves that set,
    whether by acknowledgment or by rejection as not our entity."

    Design: Difficulty/dual_variant_calc/sop_forward_deadline_ordinary_versus_litigation
    """
    scene = setup_active_home_registration(DE_RULE_FULL)
    set_clock("2026-06-05T14:00:00Z")

    litigation = validate_success(
        api.create_sop_document(
            scene["registration"]["id"],
            {
                "sop_class": "LITIGATION",
                "plaintiff_name": "Acme Trading Co",
                "court_case_number": "N26C-0417",
            },
            SOP,
        ),
        201,
    )
    ordinary = receive_sop(scene["registration"]["id"], "ORDINARY")

    assert_same_instant(
        litigation["received_at"], "2026-06-05T14:00:00Z", "litigation received_at"
    )
    assert_same_instant(
        ordinary["received_at"], "2026-06-05T14:00:00Z", "ordinary received_at"
    )
    # The litigation papers were recorded first, so no ordinary sibling existed to be
    # pre-empted and the ordinary document is never deferred.
    assert ordinary["deferred"] is False
    assert ordinary["deferral_count"] == 0
    assert read_registration(scene["registration"]["id"])["sop_priority_hold"] is True
