"""Composite setup chains built only from endpoints the contract publishes.

The server is restarted between tests, so nothing here may assume a row survives
from an earlier test. Every helper starts from an empty store, walks the same
creation path a real client would walk, and returns the rows it created so the
test can assert against them.

The chain is a ladder: each ``setup_*`` function calls the one below it when it is
handed no ``Deal``, so a test asks for the furthest stage it needs and gets every
earlier stage for free. A ``plan`` of keyword arguments threads down the ladder,
which is how one ladder serves both the four-unit development and the ten-unit
one, and how a test bends a single figure — an award amount, a draw period, a
certified basis — without re-writing the whole chain.

Preconditions use the lenient success reader so a fixture never masks the
assertion the test itself is making.
"""

from prd_bench_local_runner.testing import get_success_data

from . import constants, factories
from .test_users import (
    ALLOCATION_OFFICER,
    COMPLIANCE_OFFICER,
    SECOND_ALLOCATION_OFFICER,
    SYSTEM_OPERATOR,
    THIRD_ALLOCATION_OFFICER,
    TRUSTEE,
    make_developer_headers,
    make_investor_headers,
)


class Deal:
    """Every row a scenario has created so far, plus the identities that own them."""

    def __init__(self, plan=None):
        self.plan = dict(plan or {})
        self.developer = None
        self.investor = None
        self.pool = None
        self.project = None
        self.units = {}
        self.agreement = None
        self.allocation = None
        self.bond_issue = None
        self.draws = {}
        self.cost_certification = None
        self.credit_allocation = None
        self.deliveries = []
        self.reports = {}
        self.inspections = []

    # ─── Identifiers ──────────────────────────────────

    @property
    def developer_id(self):
        return self.developer["id"]

    @property
    def investor_id(self):
        return self.investor["id"]

    @property
    def pool_id(self):
        return self.pool["id"]

    @property
    def project_id(self):
        return self.project["id"]

    @property
    def agreement_id(self):
        return self.agreement["id"]

    @property
    def allocation_id(self):
        return self.allocation["id"]

    @property
    def bond_issue_id(self):
        return self.bond_issue["id"]

    @property
    def cost_certification_id(self):
        return self.cost_certification["id"]

    @property
    def credit_allocation_id(self):
        return self.credit_allocation["id"]

    @property
    def delivery(self):
        return self.deliveries[-1]

    @property
    def delivery_id(self):
        return self.deliveries[-1]["id"]

    # ─── Identity threading (PRD §2.1) ────────────────

    @property
    def developer_headers(self):
        """The sponsor acting as itself; ownership compares this to developer_id."""
        return make_developer_headers(self.developer_id)

    @property
    def investor_headers(self):
        """The investor acting as itself; ownership compares this to investor_id."""
        return make_investor_headers(self.investor_id)

    # ─── Convenience readers over already-fetched rows ─

    def unit(self, unit_number):
        return self.units[unit_number]

    def unit_id(self, unit_number):
        return self.units[unit_number]["id"]

    def draw(self, draw_number=1):
        return self.draws[draw_number]

    def draw_id(self, draw_number=1):
        return self.draws[draw_number]["id"]

    @property
    def total_units(self):
        return self.project["total_units"]

    @property
    def restricted_floor_spaces(self):
        """Floor areas of the development's restricted rows, by unit number."""
        return [
            unit["floor_space_sqft"]
            for _, unit in sorted(self.units.items())
            if unit["designation"] == "RESTRICTED"
        ]


def _plan(deal, key, default=None):
    return deal.plan.get(key, default)


def _merged(base, overrides):
    payload = dict(base)
    payload.update(overrides or {})
    return payload


# ─── The logical clock ────────────────────────────────


def set_clock(api, when):
    """Move the logical clock, which every deadline and window comparison reads."""
    return get_success_data(api.set_clock(when, headers=SYSTEM_OPERATOR))


def reset_clock(api):
    """Return the clock to the instant the process starts from."""
    return set_clock(api, constants.CLOCK_START_UTC)


# ─── Re-reads that refresh a Deal in place ────────────


def read_developer(api, deal):
    deal.developer = get_success_data(
        api.get_developer(deal.developer_id, ALLOCATION_OFFICER)
    )
    return deal.developer


def read_investor(api, deal):
    deal.investor = get_success_data(
        api.get_investor(deal.investor_id, ALLOCATION_OFFICER)
    )
    return deal.investor


def read_pool(api, deal):
    """The single-pool fetch, which is also the read that supplies the pool version."""
    deal.pool = get_success_data(api.get_cap_pool(deal.pool_id, ALLOCATION_OFFICER))
    return deal.pool


def pool_version(api, deal):
    return read_pool(api, deal)["version"]


def read_project(api, deal):
    deal.project = get_success_data(
        api.get_project(deal.project_id, deal.developer_headers)
    )
    return deal.project


def read_agreement(api, deal):
    deal.agreement = get_success_data(
        api.get_regulatory_agreement(deal.agreement_id, deal.developer_headers)
    )
    return deal.agreement


def read_allocation(api, deal):
    deal.allocation = get_success_data(
        api.get_volume_cap_allocation(deal.allocation_id, ALLOCATION_OFFICER)
    )
    return deal.allocation


def read_bond_issue(api, deal):
    """The single-issue fetch, which supplies the expected version for a draw."""
    deal.bond_issue = get_success_data(
        api.get_bond_issue(deal.bond_issue_id, deal.developer_headers)
    )
    return deal.bond_issue


def bond_issue_version(api, deal):
    return read_bond_issue(api, deal)["version"]


def read_units(api, deal):
    """Refresh every unit designation of the development."""
    for unit_number, unit in list(deal.units.items()):
        deal.units[unit_number] = get_success_data(
            api.get_unit_restriction(unit["id"], deal.developer_headers)
        )
    return deal.units


def read_unit(api, deal, unit_number):
    deal.units[unit_number] = get_success_data(
        api.get_unit_restriction(deal.unit_id(unit_number), deal.developer_headers)
    )
    return deal.units[unit_number]


def read_draw(api, deal, draw_number=1):
    deal.draws[draw_number] = get_success_data(
        api.get_draw_request(deal.draw_id(draw_number), deal.developer_headers)
    )
    return deal.draws[draw_number]


def read_cost_certification(api, deal):
    deal.cost_certification = get_success_data(
        api.get_cost_certification(deal.cost_certification_id, deal.developer_headers)
    )
    return deal.cost_certification


def read_credit_allocation(api, deal):
    """The single-allocation fetch, which supplies the version for a delivery."""
    deal.credit_allocation = get_success_data(
        api.get_credit_allocation(deal.credit_allocation_id, deal.developer_headers)
    )
    return deal.credit_allocation


def credit_allocation_version(api, deal):
    return read_credit_allocation(api, deal)["version"]


def read_delivery(api, deal, index=-1):
    delivery = deal.deliveries[index]
    refreshed = get_success_data(
        api.get_investor_delivery(delivery["id"], deal.developer_headers)
    )
    deal.deliveries[index] = refreshed
    return refreshed


# ─── Stage 1: the registry — sponsor, investor, pool ───


def setup_registry(api, deal=None, **plan):
    """A sponsor, an investor and one program-year pool, all freshly created.

    Nothing here is development-specific, so every later stage begins from it.
    """
    if deal is None:
        deal = Deal(plan)
    deal.pool = get_success_data(
        api.create_cap_pool(
            ALLOCATION_OFFICER,
            **_merged(factories.cap_pool_payload(), _plan(deal, "pool_overrides")),
        )
    )
    deal.developer = get_success_data(
        api.create_developer(
            ALLOCATION_OFFICER,
            **_merged(
                factories.developer_payload(), _plan(deal, "developer_overrides")
            ),
        )
    )
    deal.investor = get_success_data(
        api.create_investor(
            ALLOCATION_OFFICER,
            **_merged(factories.investor_payload(), _plan(deal, "investor_overrides")),
        )
    )
    return deal


def register_second_developer(api, **overrides):
    """An unrelated sponsor, used as the foreign owner in ownership probes."""
    return get_success_data(
        api.create_developer(
            ALLOCATION_OFFICER, **factories.second_developer_payload(**overrides)
        )
    )


def register_second_investor(api, **overrides):
    return get_success_data(
        api.create_investor(
            ALLOCATION_OFFICER, **factories.second_investor_payload(**overrides)
        )
    )


# ─── Stage 2: the development ─────────────────────────


def _project_payload(deal):
    kind = _plan(deal, "project_kind", "compact")
    if kind == "ten_unit":
        base = factories.ten_unit_project_payload(deal.developer_id)
    else:
        base = factories.compact_project_payload(deal.developer_id)
    return _merged(base, _plan(deal, "project_overrides"))


def setup_project(api, deal=None, **plan):
    """The development itself, filed by its own sponsor, still ``PLANNED``."""
    if deal is None:
        deal = setup_registry(api, **plan)
    deal.project = get_success_data(
        api.create_project(deal.developer_headers, **_project_payload(deal))
    )
    return deal


def file_second_project(api, deal, **overrides):
    """A sibling development under the same sponsor, for cross-development probes."""
    payload = factories.compact_project_payload(deal.developer_id, **overrides)
    return get_success_data(api.create_project(deal.developer_headers, **payload))


def designate_unit(api, deal, **spec):
    """Designate one more unit of the development and remember it by unit number."""
    payload = factories.unit_payload(deal.project_id, **spec)
    row = get_success_data(api.create_unit_restriction(deal.developer_headers, **payload))
    deal.units[row["unit_number"]] = row
    return row


def setup_units(api, deal=None, **plan):
    """Every unit of the roster designated, so the fractions and counters are settled."""
    if deal is None:
        deal = setup_project(api, **plan)
    roster = _plan(deal, "roster")
    if roster is None:
        roster = (
            factories.TEN_UNIT_ROSTER
            if _plan(deal, "project_kind", "compact") == "ten_unit"
            else factories.COMPACT_ROSTER
        )
    for spec in roster:
        payload = dict(spec, project_id=deal.project_id)
        row = get_success_data(
            api.create_unit_restriction(deal.developer_headers, **payload)
        )
        deal.units[row["unit_number"]] = row
    read_project(api, deal)
    return deal


# ─── Stage 3: the regulatory agreement ────────────────


def setup_drafted_agreement(api, deal=None, **plan):
    """A ``DRAFT`` agreement whose election matches the development's."""
    if deal is None:
        deal = setup_units(api, **plan)
    base = factories.agreement_payload(
        deal.project_id, set_aside_election=deal.project["set_aside_election"]
    )
    deal.agreement = get_success_data(
        api.create_regulatory_agreement(
            deal.developer_headers, **_merged(base, _plan(deal, "agreement_overrides"))
        )
    )
    return deal


def setup_recorded_agreement(api, deal=None, **plan):
    """The agreement recorded, which is what lets the bonds be issued later."""
    if deal is None:
        deal = setup_drafted_agreement(api, **plan)
    deal.agreement = get_success_data(
        api.record_regulatory_agreement(
            deal.agreement_id,
            COMPLIANCE_OFFICER,
            instrument_number=_plan(
                deal, "instrument_number", constants.INSTRUMENT_NUMBER
            ),
        )
    )
    read_project(api, deal)
    return deal


def amend_agreement(api, deal, amendment_reason="extend the extended-use term",
                    **overrides):
    """Open an amendment, which parks the agreement in ``AMENDMENT_PENDING``."""
    deal.agreement = get_success_data(
        api.amend_regulatory_agreement(
            deal.agreement_id,
            COMPLIANCE_OFFICER,
            amendment_reason=amendment_reason,
            **overrides,
        )
    )
    return deal.agreement


def rerecord_agreement(api, deal, instrument_number=None, **overrides):
    """Re-record a pending amendment, which is what makes the amendment take effect."""
    if instrument_number is None:
        instrument_number = constants.INSTRUMENT_NUMBER
    deal.agreement = get_success_data(
        api.record_regulatory_agreement(
            deal.agreement_id,
            COMPLIANCE_OFFICER,
            instrument_number=instrument_number,
            **overrides,
        )
    )
    return deal.agreement


# ─── Stage 4: the volume cap allocation ───────────────


def request_cap(api, deal, **overrides):
    """File one more cap request against the pool and return the raw row."""
    payload = factories.cap_request_payload(deal.project_id, deal.pool_id, **overrides)
    return get_success_data(
        api.create_volume_cap_allocation(deal.developer_headers, **payload)
    )


def setup_cap_request(api, deal=None, **plan):
    """A ``PENDING`` request, whose amount is already reserved against the pool."""
    if deal is None:
        deal = setup_recorded_agreement(api, **plan)
    base = factories.cap_request_payload(deal.project_id, deal.pool_id)
    deal.allocation = get_success_data(
        api.create_volume_cap_allocation(
            deal.developer_headers, **_merged(base, _plan(deal, "cap_request_overrides"))
        )
    )
    read_pool(api, deal)
    return deal


def setup_awarded_cap(api, deal=None, **plan):
    """The request awarded, so the pool counts it as committed rather than reserved."""
    if deal is None:
        deal = setup_cap_request(api, **plan)
    base = factories.award_payload(pool_version(api, deal))
    deal.allocation = get_success_data(
        api.decide_volume_cap_allocation(
            deal.allocation_id,
            ALLOCATION_OFFICER,
            **_merged(base, _plan(deal, "award_overrides")),
        )
    )
    read_pool(api, deal)
    read_project(api, deal)
    return deal


def award_allocation(api, deal, allocation_id, **overrides):
    """Award some other allocation of the same pool, reading the pool version first."""
    payload = factories.award_payload(pool_version(api, deal), **overrides)
    row = get_success_data(
        api.decide_volume_cap_allocation(allocation_id, ALLOCATION_OFFICER, **payload)
    )
    read_pool(api, deal)
    return row


def deny_allocation(api, deal, allocation_id, **overrides):
    payload = factories.denial_payload(pool_version(api, deal), **overrides)
    row = get_success_data(
        api.decide_volume_cap_allocation(allocation_id, ALLOCATION_OFFICER, **payload)
    )
    read_pool(api, deal)
    return row


def return_allocation(api, deal, allocation_id=None,
                      return_reason="closing deferred to next year", **overrides):
    if allocation_id is None:
        allocation_id = deal.allocation_id
    row = get_success_data(
        api.return_volume_cap_allocation(
            allocation_id,
            deal.developer_headers,
            return_reason=return_reason,
            **overrides,
        )
    )
    read_pool(api, deal)
    return row


# ─── Stage 5: the bond issue ──────────────────────────


def setup_sized_bond(api, deal=None, **plan):
    """A ``DRAFT`` issue, already solved through the sizing chain of PRD §3.5."""
    if deal is None:
        deal = setup_awarded_cap(api, **plan)
    base = factories.bond_issue_payload(deal.project_id, deal.allocation_id)
    deal.bond_issue = get_success_data(
        api.create_bond_issue(
            deal.developer_headers, **_merged(base, _plan(deal, "bond_overrides"))
        )
    )
    return deal


def setup_issued_bond(api, deal=None, **plan):
    """The bonds closed: development ``FINANCED``, award ``COMMITTED``, units ``ACTIVE``."""
    if deal is None:
        deal = setup_sized_bond(api, **plan)
    deal.bond_issue = get_success_data(
        api.issue_bond_issue(
            deal.bond_issue_id,
            TRUSTEE,
            closing_date=_plan(deal, "closing_date", constants.CLOSING_DATE),
        )
    )
    read_project(api, deal)
    read_allocation(api, deal)
    read_pool(api, deal)
    read_units(api, deal)
    return deal


def submit_draw(api, deal, **overrides):
    """Submit one draw, reading the issue version immediately beforehand."""
    payload = factories.draw_payload(
        deal.bond_issue_id, bond_issue_version(api, deal), **overrides
    )
    row = get_success_data(api.create_draw_request(deal.developer_headers, **payload))
    deal.draws[row["draw_number"]] = row
    return row


def approve_draw(api, deal, draw_number=1, approved_amount_cents=None):
    """Approve a submitted draw for its requested amount unless told otherwise."""
    draw = deal.draws[draw_number]
    if approved_amount_cents is None:
        approved_amount_cents = draw["requested_amount_cents"]
    row = get_success_data(
        api.decide_draw_request(
            draw["id"],
            TRUSTEE,
            decision="APPROVE",
            approved_amount_cents=approved_amount_cents,
        )
    )
    deal.draws[draw_number] = row
    return row


def reject_draw(api, deal, draw_number=1, rejection_reason="documentation incomplete"):
    draw = deal.draws[draw_number]
    row = get_success_data(
        api.decide_draw_request(
            draw["id"], TRUSTEE, decision="REJECT", rejection_reason=rejection_reason
        )
    )
    deal.draws[draw_number] = row
    return row


def fund_draw(api, deal, draw_number=1, funding_date=None):
    """Fund an approved draw, which is the act that re-prices negative arbitrage."""
    draw = deal.draws[draw_number]
    if funding_date is None:
        funding_date = draw["period_start"]
    row = get_success_data(
        api.fund_draw_request(draw["id"], TRUSTEE, funding_date=funding_date)
    )
    deal.draws[draw_number] = row
    read_bond_issue(api, deal)
    return row


def void_draw(api, deal, draw_number=1, void_reason="requisition withdrawn"):
    draw = deal.draws[draw_number]
    row = get_success_data(
        api.void_draw_request(draw["id"], TRUSTEE, void_reason=void_reason)
    )
    deal.draws[draw_number] = row
    read_bond_issue(api, deal)
    return row


def walk_draw(api, deal, **overrides):
    """Submit, approve and fund one draw in a single call, returning the funded row."""
    row = submit_draw(api, deal, **overrides)
    number = row["draw_number"]
    approve_draw(api, deal, number)
    return fund_draw(api, deal, number)


def setup_funded_draw(api, deal=None, **plan):
    """One draw funded for the whole par, which is what the fifty-percent test reads."""
    if deal is None:
        deal = setup_issued_bond(api, **plan)
    walk_draw(api, deal, **(_plan(deal, "draw_overrides") or {}))
    read_project(api, deal)
    return deal


# ─── Stage 6: operating history and conversion ────────


def record_month(api, deal, month_index, **overrides):
    """Record one operating month; the first one places the development in service."""
    spec = {"occupied_units": deal.total_units}
    spec.update(overrides)
    payload = factories.operating_month_payload(month_index, **spec)
    deal.bond_issue = get_success_data(
        api.record_operating_month(deal.bond_issue_id, deal.developer_headers, **payload)
    )
    return deal.bond_issue


def setup_operating_months(api, deal=None, count=3, **plan):
    """Enough consecutive months for the trailing window the conversion test reads."""
    if deal is None:
        deal = setup_funded_draw(api, **plan)
    overrides = _plan(deal, "operating_month_overrides") or {}
    for month_index in range(1, count + 1):
        record_month(api, deal, month_index, **overrides)
    read_project(api, deal)
    return deal


def setup_placed_in_service(api, deal=None, **plan):
    """The single month that flips the development to ``PLACED_IN_SERVICE``."""
    if deal is None:
        deal = setup_funded_draw(api, **plan)
    record_month(api, deal, 1, **(_plan(deal, "operating_month_overrides") or {}))
    read_project(api, deal)
    return deal


def setup_converted_bond(api, deal=None, dscr_basis="T3", **plan):
    """Permanent conversion: development ``STABILIZED`` and the compliance clock started."""
    if deal is None:
        deal = setup_operating_months(api, count=3, **plan)
    base = {
        "conversion_date": _plan(deal, "conversion_date", constants.CONVERSION_DATE),
        "dscr_basis": dscr_basis,
    }
    deal.bond_issue = get_success_data(
        api.convert_bond_issue(
            deal.bond_issue_id,
            TRUSTEE,
            **_merged(base, _plan(deal, "conversion_overrides")),
        )
    )
    read_project(api, deal)
    read_agreement(api, deal)
    read_units(api, deal)
    return deal


def redeem_bond(api, deal, redemption_date=None, reason="construction abandoned"):
    """The trustee's unwind, which withdraws the development and frees the cap."""
    if redemption_date is None:
        redemption_date = constants.CONVERSION_DATE
    deal.bond_issue = get_success_data(
        api.mandatory_redeem_bond_issue(
            deal.bond_issue_id, TRUSTEE, redemption_date=redemption_date, reason=reason
        )
    )
    read_project(api, deal)
    read_allocation(api, deal)
    read_pool(api, deal)
    return deal.bond_issue


# ─── Stage 7: the cost certification ──────────────────


def setup_drafted_cost_certification(api, deal=None, **plan):
    """A ``DRAFT`` certification over a development that is already in service."""
    if deal is None:
        deal = setup_operating_months(api, count=3, **plan)
    base = factories.cost_certification_payload(deal.project_id)
    deal.cost_certification = get_success_data(
        api.create_cost_certification(
            deal.developer_headers, **_merged(base, _plan(deal, "cost_cert_overrides"))
        )
    )
    return deal


def submit_cost_certification(api, deal, **overrides):
    """Submit for agency review, which raises ``submission_round`` by one."""
    deal.cost_certification = get_success_data(
        api.submit_cost_certification(
            deal.cost_certification_id, deal.developer_headers, **overrides
        )
    )
    return deal.cost_certification


def review_cost_certification(api, deal, decision="ACCEPT", headers=None, **overrides):
    """Accept or return the certification; acceptance runs the final variant test."""
    if headers is None:
        headers = SECOND_ALLOCATION_OFFICER
    deal.cost_certification = get_success_data(
        api.review_cost_certification(
            deal.cost_certification_id, headers, decision=decision, **overrides
        )
    )
    read_project(api, deal)
    return deal.cost_certification


def setup_submitted_cost_certification(api, deal=None, **plan):
    if deal is None:
        deal = setup_drafted_cost_certification(api, **plan)
    submit_cost_certification(api, deal)
    return deal


def setup_accepted_cost_certification(api, deal=None, **plan):
    """The certification accepted, which is what the final allocation is computed from."""
    if deal is None:
        deal = setup_submitted_cost_certification(api, **plan)
    review_cost_certification(api, deal, decision="ACCEPT")
    return deal


# ─── Stage 8: the credit allocation and its deliveries ─


def setup_credit_allocation(api, deal=None, **plan):
    """A ``PENDING`` allocation with the qualified basis and annual credit solved."""
    if deal is None:
        deal = setup_accepted_cost_certification(api, **plan)
    base = factories.credit_allocation_payload(
        deal.project_id, deal.cost_certification_id
    )
    deal.credit_allocation = get_success_data(
        api.create_credit_allocation(
            THIRD_ALLOCATION_OFFICER,
            **_merged(base, _plan(deal, "credit_allocation_overrides")),
        )
    )
    return deal


def setup_issued_credit_allocation(api, deal=None, **plan):
    """The certificate issued by a third officer, so the credit becomes deliverable."""
    if deal is None:
        deal = setup_credit_allocation(api, **plan)
    deal.credit_allocation = get_success_data(
        api.issue_credit_allocation(
            deal.credit_allocation_id,
            THIRD_ALLOCATION_OFFICER,
            form_8609_number=_plan(deal, "form_8609_number", constants.FORM_8609_NUMBER),
        )
    )
    return deal


def deliver_credit(api, deal, investor_id=None, **overrides):
    """Create one delivery, reading the allocation version immediately beforehand."""
    if investor_id is None:
        investor_id = deal.investor_id
    payload = factories.delivery_payload(
        deal.credit_allocation_id,
        investor_id,
        credit_allocation_version(api, deal),
        **overrides,
    )
    row = get_success_data(api.create_investor_delivery(deal.developer_headers, **payload))
    deal.deliveries.append(row)
    read_credit_allocation(api, deal)
    return row


def accept_delivery(api, deal, index=-1, headers=None):
    """The investor's own act, confined to deliveries naming that investor."""
    delivery = deal.deliveries[index]
    if headers is None:
        headers = make_investor_headers(delivery["investor_id"])
    row = get_success_data(api.accept_investor_delivery(delivery["id"], headers))
    deal.deliveries[index] = row
    read_investor(api, deal)
    return row


def rescind_delivery(api, deal, index=-1, rescind_reason="syndication restructured"):
    delivery = deal.deliveries[index]
    row = get_success_data(
        api.rescind_investor_delivery(
            delivery["id"], deal.developer_headers, rescind_reason=rescind_reason
        )
    )
    deal.deliveries[index] = row
    read_credit_allocation(api, deal)
    return row


def setup_delivered_credit(api, deal=None, **plan):
    """One delivery outstanding in ``DELIVERED`` against an issued allocation."""
    if deal is None:
        deal = setup_issued_credit_allocation(api, **plan)
    deliver_credit(api, deal, **(_plan(deal, "delivery_overrides") or {}))
    return deal


def setup_accepted_delivery(api, deal=None, **plan):
    """A delivery the investor has accepted, which is what a recapture flags later."""
    if deal is None:
        deal = setup_delivered_credit(api, **plan)
    accept_delivery(api, deal)
    return deal


# ─── Stage 9: ongoing compliance and inspections ──────


def file_compliance_report(api, deal, reporting_year=2027, **overrides):
    """File one annual owner certification and remember it by reporting year."""
    spec = {"total_units_occupied": deal.total_units}
    spec.update(overrides)
    payload = factories.compliance_report_payload(
        deal.project_id, reporting_year=reporting_year, **spec
    )
    row = get_success_data(api.create_compliance_report(deal.developer_headers, **payload))
    deal.reports[row["reporting_year"]] = row
    return row


def review_compliance_report(api, deal, reporting_year=2027, finding="CLEARED",
                             finding_notes=None, **overrides):
    """Review a filed report; a noncompliance finding fires the three-level cascade."""
    report = deal.reports[reporting_year]
    body = dict(overrides)
    if finding_notes is not None:
        body["finding_notes"] = finding_notes
    row = get_success_data(
        api.review_compliance_report(
            report["id"], COMPLIANCE_OFFICER, finding=finding, **body
        )
    )
    deal.reports[reporting_year] = row
    read_project(api, deal)
    return row


def setup_noncompliance_finding(api, deal=None, reporting_year=2027,
                                restricted_units_occupied=0, **plan):
    """A shortfall filed and found, so the development sits in ``NONCOMPLIANT``."""
    if deal is None:
        deal = setup_accepted_delivery(api, **plan)
    file_compliance_report(
        api,
        deal,
        reporting_year=reporting_year,
        restricted_units_occupied=restricted_units_occupied,
    )
    review_compliance_report(
        api,
        deal,
        reporting_year=reporting_year,
        finding="NONCOMPLIANCE",
        finding_notes="set-aside not met at year end",
    )
    read_credit_allocation(api, deal)
    read_delivery(api, deal)
    return deal


def schedule_inspection(api, deal, **overrides):
    """Schedule one inspection window and remember the row."""
    payload = factories.inspection_payload(deal.project_id, **overrides)
    row = get_success_data(
        api.create_physical_inspection(COMPLIANCE_OFFICER, **payload)
    )
    deal.inspections.append(row)
    return row


def complete_inspection(api, deal, index=-1, completed_date=None, score=92,
                        deficiency_count=1, **overrides):
    """Record a result, which stamps the three-year next-due date."""
    inspection = deal.inspections[index]
    if completed_date is None:
        completed_date = inspection["window_start"]
    row = get_success_data(
        api.complete_physical_inspection(
            inspection["id"],
            COMPLIANCE_OFFICER,
            completed_date=completed_date,
            score=score,
            deficiency_count=deficiency_count,
            **overrides,
        )
    )
    deal.inspections[index] = row
    return row


# ─── Named whole-deal shortcuts ───────────────────────

TEN_UNIT_PLAN = {"project_kind": "ten_unit"}


def ten_unit_deal(api, stage=setup_units, **plan):
    """The ten-unit development, whose two fractions deliberately disagree."""
    merged = dict(TEN_UNIT_PLAN)
    merged.update(plan)
    return stage(api, **merged)
